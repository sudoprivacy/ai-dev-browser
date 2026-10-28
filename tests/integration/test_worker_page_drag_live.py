"""Live page feedback and input cleanup through the authenticated worker API."""

import asyncio
import base64
import json
import os
from importlib.resources import files
from io import BytesIO
from pathlib import Path
import secrets
from uuid import uuid4

import aiohttp
import pytest
from aiohttp import web
from PIL import Image

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.remote.worker import Worker, application
from tests.integration.test_remote_view import connect_page, wait_for

pytest_plugins = ["tests.integration.test_remote_view"]


@pytest.mark.parametrize("transport", ["cdp", "extension"])
async def test_headless_page_drag_updates_pixels_before_release(
    tmp_path, remote_site, transport
):
    extension = Path("/opt/browser/extension")
    if transport == "extension" and not (extension / "identity.json").is_file():
        pytest.skip("Signed managed extension policy fixture required")
    host_token, ai_token = secrets.token_hex(32), secrets.token_hex(32)
    worker = Worker(
        tmp_path / "worker",
        host_token,
        ai_token,
        extension_directory=extension if transport == "extension" else None,
        chrome_args=["--no-sandbox"] if os.name != "nt" else [],
    )
    runner = web.AppRunner(application(worker))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8080 if transport == "extension" else 0)
    await site.start()
    origin = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    binding = {"orgId": "page-live-fixture", "userId": "owner", "sessionId": "review"}
    controller, viewer = "user-page-owner", str(uuid4())
    gesture = uuid4().hex
    viewer_browser = viewer_page = viewer_runner = None

    def epochs(state):
        return {key: state[key] for key in ("controlEpoch", "targetEpoch")}

    async with aiohttp.ClientSession() as http:

        async def host(action):
            async with http.post(
                origin + "/invoke",
                headers={"Authorization": "Bearer " + host_token},
                json={"binding": binding, "controller": controller, "action": action},
            ) as response:
                value = await response.json()
                assert response.status == 200, (response.status, value)
                return value

        async def source():
            page = await worker.session._connect_page()
            return await page.js("({pan,events:panEvents})")

        try:
            state = (
                await host(
                    {"kind": "start", "isHeadless": True, "transport": transport}
                )
            )["session"]
            state = (
                await host(
                    {
                        "kind": "navigate",
                        "url": remote_site[0] + "/native-drag",
                        **epochs(state),
                    }
                )
            )["session"]
            await host({"kind": "attach", "viewerId": viewer, "surface": "page"})
            initial = await host(
                {
                    "kind": "frame",
                    "viewerId": viewer,
                    "surface": "page",
                    **epochs(state),
                }
            )
            assert "page" in initial["session"]["capabilities"].get(
                "liveDragSurfaces", []
            )
            assert worker.display is None, (
                "Headless page input must not allocate an X display"
            )

            async def drag(phase, sequence, x, y):
                return await host(
                    {
                        "kind": "input",
                        "surface": "page",
                        **epochs(state),
                        "input": {
                            "kind": "drag-stream",
                            "phase": phase,
                            "sequence": sequence,
                            "gestureId": gesture,
                            "viewerId": viewer,
                            "x": x,
                            "y": y,
                        },
                    }
                )

            await drag("begin", 0, 500, 250)
            await drag("move", 1, 400, 200)
            held = await source()
            assert held["pan"] == {"x": -100, "y": -50}
            assert held["events"] and all(event["trusted"] for event in held["events"])
            assert not any(event["kind"] == "pointerup" for event in held["events"])
            frame = await asyncio.wait_for(
                host(
                    {
                        "kind": "frame",
                        "viewerId": viewer,
                        "surface": "page",
                        **epochs(state),
                    }
                ),
                timeout=3,
            )
            pixels = Image.open(
                BytesIO(base64.b64decode(frame["frame"]["data"]))
            ).convert("RGB")
            assert all(
                abs(actual - expected) < 12
                for actual, expected in zip(
                    pixels.getpixel((140, 110)), (102, 187, 153)
                )
            )
            assert not any(
                event["kind"] == "pointerup" for event in (await source())["events"]
            )
            await drag("end", 2, 400, 200)
            assert (
                sum(
                    event["kind"] == "pointerup" for event in (await source())["events"]
                )
                == 1
            )

            # Closing a page viewer releases its unfinished press and retains
            # the same human owner; it cannot silently authorize the agent.
            gesture = uuid4().hex
            await drag("begin", 0, 500, 250)
            await drag("move", 1, 450, 225)
            detached = await host({"kind": "detach", "viewerId": viewer})
            assert worker.live_drag is None
            assert detached["session"]["state"] == "human"
            assert detached["session"]["isHumanControlHeld"] is True
            assert detached["session"]["controlEpoch"] > state["controlEpoch"]
            assert (
                sum(
                    event["kind"] == "pointerup" for event in (await source())["events"]
                )
                == 2
            )

            # Drive the shipped PageSurface from a second real Chrome. The
            # test host owns authentication; its viewer receives no worker key.
            state = (
                await host(
                    {
                        "kind": "navigate",
                        "url": remote_site[0] + "/native-drag",
                        **epochs(detached["session"]),
                    }
                )
            )["session"]
            await host({"kind": "attach", "viewerId": viewer, "surface": "page"})

            async def viewer_html(request):
                return web.Response(
                    content_type="text/html",
                    text="""<!doctype html>
                <img id="screen" tabindex="0" style="display:block;width:640px;touch-action:none">
                <script type="module">
                import {PageSurface} from '/surface.js';
                window.packets=[];window.errors=[];
                window.surface=new PageSurface(document.querySelector('#screen'), async input=>{
                  packets.push(input);
                  const response=await fetch('/input',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(input)});
                  if(!response.ok)throw Error(await response.text());
                  return response.json();
                }, {drag:true,liveDrag:true,viewerId:VIEWER});
                async function poll(){try{
                  const response=await fetch('/frame');
                  if(!response.ok)throw Error(await response.text());
                  surface.frame((await response.json()).frame);
                }catch(error){errors.push(String(error));}setTimeout(poll,100)}poll();
                </script>""".replace("VIEWER", json.dumps(viewer)),
                )

            async def surface_asset(request):
                return web.FileResponse(files("ai_dev_browser.remote") / "page_view.js")

            async def checked_input(request):
                value = await host(
                    {
                        "kind": "input",
                        "surface": "page",
                        "input": await request.json(),
                        **epochs(state),
                    }
                )
                return web.json_response(value)

            async def checked_frame(request):
                value = await host(
                    {
                        "kind": "frame",
                        "surface": "page",
                        "viewerId": viewer,
                        **epochs(state),
                    }
                )
                return web.json_response(value)

            app = web.Application()
            app.add_routes(
                [
                    web.get("/", viewer_html),
                    web.get("/surface.js", surface_asset),
                    web.post("/input", checked_input),
                    web.get("/frame", checked_frame),
                ]
            )
            viewer_runner = web.AppRunner(app)
            await viewer_runner.setup()
            viewer_site = web.TCPSite(viewer_runner, "127.0.0.1", 0)
            await viewer_site.start()
            viewer_browser = await asyncio.to_thread(
                browser_start,
                headless=True,
                stealth=False,
                extra_args=worker.chrome_args,
            )
            viewer_page, _ = await connect_page(
                http, viewer_browser["port"], viewer_browser["automation_target_id"]
            )
            await viewer_page.call(
                "Page.navigate",
                {
                    "url": f"http://127.0.0.1:{viewer_site._server.sockets[0].getsockname()[1]}"
                },
            )
            rect = await wait_for(
                lambda: viewer_page.js(
                    """(()=>{const i=document.querySelector('#screen');if(!i?.complete||!i.naturalWidth)return null;const r=i.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,w:surface.width,h:surface.height}})()"""
                ),
                bool,
            )

            async def pointer(kind, x, y):
                await viewer_page.call(
                    "Input.dispatchMouseEvent",
                    {
                        "type": kind,
                        "x": rect["x"] + x * rect["width"] / rect["w"],
                        "y": rect["y"] + y * rect["height"] / rect["h"],
                        "button": "left",
                        "buttons": 0 if kind == "mouseReleased" else 1,
                        **({"clickCount": 1} if kind != "mouseMoved" else {}),
                    },
                )

            await pointer("mouseMoved", 500, 250)
            await pointer("mousePressed", 500, 250)
            motion_started = await viewer_page.js("performance.now()")
            await pointer("mouseMoved", 400, 200)
            visible = await wait_for(
                lambda: viewer_page.js(
                    """(()=>{const i=document.querySelector('#screen');if(!i?.complete||!i.naturalWidth)return null;const c=document.createElement('canvas');c.width=i.naturalWidth;c.height=i.naturalHeight;const x=c.getContext('2d');x.drawImage(i,0,0);return Array.from(x.getImageData(140,110,1,1).data).slice(0,3)})()"""
                ),
                lambda rgb: rgb
                and all(abs(a - b) < 12 for a, b in zip(rgb, (102, 187, 153))),
            )
            held_ui = await source()
            # Scaled CSS coordinates cross CDP's floating point conversion.
            # Keep subpixel precision; never accept a missing/partial gesture.
            assert held_ui["pan"] == pytest.approx({"x": -100, "y": -50}, abs=0.0001)
            assert not any(event["kind"] == "pointerup" for event in held_ui["events"])
            (tmp_path / "page-drag-held.png").write_bytes(
                base64.b64decode(
                    (await viewer_page.call("Page.captureScreenshot"))["data"]
                )
            )
            metrics = {
                "transport": transport,
                "pixelsWhileHeld": visible,
                "sourceWhileHeld": held_ui,
                "motionToVisibleUpperBoundMs": (
                    await viewer_page.js("performance.now()")
                )
                - motion_started,
            }
            await pointer("mouseReleased", 400, 200)
            await wait_for(
                lambda: source(),
                lambda value: sum(e["kind"] == "pointerup" for e in value["events"])
                == 1,
            )
            await wait_for(lambda: viewer_page.js("surface.gesture === null"), bool)
            metrics["packets"] = await viewer_page.js("packets")
            metrics["viewerErrors"] = await viewer_page.js("errors")
            assert not metrics["viewerErrors"]
            assert [p["phase"] for p in metrics["packets"]] == ["begin", "move", "end"]
            (tmp_path / "page-drag.json").write_text(json.dumps(metrics, indent=2))
        except Exception:
            if viewer_page:
                (tmp_path / "page-drag-failure.png").write_bytes(
                    base64.b64decode(
                        (await viewer_page.call("Page.captureScreenshot"))["data"]
                    )
                )
                (tmp_path / "page-drag-failure.json").write_text(
                    json.dumps(
                        {
                            "source": await source(),
                            "viewer": await viewer_page.js(
                                "({packets:window.packets,errors:window.errors})"
                            ),
                        },
                        indent=2,
                    )
                )
            raise
        finally:
            try:
                if viewer_page:
                    await viewer_page.close()
                if viewer_browser:
                    stopped = await asyncio.to_thread(
                        browser_stop, session_id=viewer_browser["session_id"]
                    )
                    assert stopped.get("stopped") is True, stopped
                if viewer_runner:
                    await viewer_runner.cleanup()
                if worker.browser:
                    current = await worker.state(controller)
                    await host({"kind": "stop", **epochs(current)})
            finally:
                await runner.cleanup()
