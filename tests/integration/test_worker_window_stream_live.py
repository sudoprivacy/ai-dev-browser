"""Real Chrome/noVNC stream: pixels, hostile raw input, guarded input and reconnect."""

import asyncio
import base64
import json
import os
import secrets
import sys
from importlib.resources import files
from pathlib import Path
from urllib.parse import quote

import aiohttp
import pytest
from aiohttp import web

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.remote.cdp import BrowserViewError
from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.worker import Worker, application
from tests.integration.test_remote_view import connect_page, wait_for

pytest_plugins = ["tests.integration.test_remote_view"]


@pytest.mark.skipif(
    sys.platform != "linux", reason="An isolated X11 display is required"
)
@pytest.mark.parametrize("transport", ["cdp", "extension"])
@pytest.mark.parametrize("touch_drag", [False, True], ids=["mouse", "touch"])
async def test_authenticated_window_stream_cannot_bypass_input_lease(
    tmp_path, remote_site, transport, touch_drag
):
    """Watch without taking control, reject raw writes, then submit through checked input.

    The test host proxy supplies the trusted worker header. This is the SDK
    transport acceptance; public tenant authentication belongs to its consumer.
    """
    extension = Path("/opt/browser/extension")
    if transport == "extension" and not (extension / "identity.json").is_file():
        pytest.skip("Signed managed extension policy fixture required")
    host_token, ai_token = secrets.token_hex(32), secrets.token_hex(32)
    worker = Worker(
        tmp_path / "worker",
        host_token,
        ai_token,
        extension_directory=extension if transport == "extension" else None,
        chrome_args=["--no-sandbox"],
    )
    runner = web.AppRunner(application(worker))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8080 if transport == "extension" else 0)
    await site.start()
    origin = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    binding = {"orgId": "stream-fixture", "userId": "owner", "sessionId": "review"}
    controller, viewer_id = "user-stream-owner", "window-fixture"
    headers = {"Authorization": "Bearer " + host_token}
    credentials, context = {}, {}
    forwarded_types = []
    viewer_browser = viewer = None
    viewer_runner = None
    clipboard = None

    def epochs(state):
        return {key: state[key] for key in ("controlEpoch", "targetEpoch")}

    async with aiohttp.ClientSession() as http:

        async def host(action, expected_error=None):
            async with http.post(
                origin + "/invoke",
                headers=headers,
                json={"binding": binding, "controller": controller, "action": action},
            ) as response:
                body = await response.json()
                assert response.status == (409 if expected_error else 200), (
                    response.status,
                    body,
                )
                if expected_error:
                    assert body["error"] == expected_error
                return body

        async def proxy(request):
            upstream_headers = {
                **headers,
                "X-ADB-Browser-Context": quote(json.dumps(context)),
            }
            async with http.ws_connect(
                origin + "/window-stream",
                headers=upstream_headers,
                protocols=("binary",),
            ) as upstream:
                downstream = web.WebSocketResponse(protocols=("binary",))
                await downstream.prepare(request)

                async def forward(source, destination, record=False):
                    async for message in source:
                        if message.type != aiohttp.WSMsgType.BINARY:
                            break
                        if record and message.data:
                            forwarded_types.append(message.data[0])
                        await destination.send_bytes(message.data)

                tasks = [
                    asyncio.create_task(forward(downstream, upstream, True)),
                    asyncio.create_task(forward(upstream, downstream)),
                ]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await downstream.close()
                return downstream

        async def viewer_html(request):
            return web.Response(
                content_type="text/html",
                text="""<!doctype html><style>html,body,#view{margin:0;width:100%;height:100%}</style>
                <div id="view"></div><script type="module">
                import RFB from '/novnc/core/rfb.js';
                const rfb=new RFB(document.querySelector('#view'),location.origin.replace('http','ws')+'/view',
                    {credentials:{password:PASSWORD}});
                window.rfb=rfb;rfb.scaleViewport=true;
                // Deliberately malicious client: only the server may enforce read-only.
                rfb.viewOnly=false;
                rfb.addEventListener('connect',()=>window.isConnected=true);
                rfb.addEventListener('disconnect',()=>window.isConnected=false);
                </script>""".replace("PASSWORD", json.dumps(credentials["password"])),
            )

        async def input_surface(request):
            return web.FileResponse(files("ai_dev_browser.remote") / "page_view.js")

        async def checked_input(request):
            reply = await host(
                {
                    "kind": "input",
                    "surface": "window",
                    "input": await request.json(),
                    "controlEpoch": context["controlEpoch"],
                    "targetEpoch": context["targetEpoch"],
                }
            )
            return web.json_response(reply)

        async def get_stream():
            credentials.clear()
            reply = await host(
                {
                    "kind": "window-stream",
                    "viewerId": viewer_id,
                    **epochs(await worker.state()),
                }
            )
            credentials.update(reply["stream"])
            assert credentials["protocol"] == "rfb" and credentials["isViewOnly"]
            context.update(
                binding=binding,
                controller=controller,
                viewerId=viewer_id,
                **epochs(reply["session"]),
            )
            return worker.window_stream._view

        try:
            async with http.get(
                origin + "/window-stream",
                headers={"Authorization": "Bearer " + ai_token},
            ) as response:
                assert response.status == 403
            await host({"kind": "state"})
            await worker.agent(
                {"kind": "start", "isHeadless": False, "transport": transport}
            )
            await worker.agent(
                {
                    "kind": "navigate",
                    "url": remote_site[0],
                    **epochs(await worker.state()),
                }
            )
            page = await worker.session._connect_page()
            await page.js("document.body.style.background='#22aa66'")
            initial = (
                await host(
                    {"kind": "attach", "viewerId": viewer_id, "surface": "window"}
                )
            )["session"]
            assert initial["state"] == "ai" and not initial["isHumanControlHeld"]
            assert initial["capabilities"]["windowStream"]
            stream = await get_stream()
            first_processes = stream.view.processes.copy()
            clipboard = await asyncio.create_subprocess_exec(
                "xclip",
                "-selection",
                "clipboard",
                "-in",
                "-loops",
                "0",
                "-verbose",
                env={**os.environ, "DISPLAY": worker.display.display},
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            clipboard.stdin.write(b"OWNED_CLIPBOARD_CANARY")
            await clipboard.stdin.drain()
            clipboard.stdin.close()
            await clipboard.stdin.wait_closed()

            async def clipboard_ready():
                while line := await clipboard.stderr.readline():
                    if b"Waiting for selection requests" in line:
                        return
                raise AssertionError("Owned clipboard did not become ready")

            await asyncio.wait_for(clipboard_ready(), 5)

            app = web.Application()
            app.add_routes(
                [
                    web.get("/", viewer_html),
                    web.get("/view", proxy),
                    web.get("/input-surface.js", input_surface),
                    web.post("/input", checked_input),
                ]
            )
            app.router.add_static("/novnc/", "/usr/share/novnc")
            viewer_runner = web.AppRunner(app)
            await viewer_runner.setup()
            viewer_site = web.TCPSite(viewer_runner, "127.0.0.1", 0)
            await viewer_site.start()
            viewer_url = (
                f"http://127.0.0.1:{viewer_site._server.sockets[0].getsockname()[1]}"
            )
            viewer_browser = await asyncio.to_thread(
                browser_start,
                headless=True,
                temp=True,
                silent_stderr=True,
                extra_args=["--no-sandbox", "--window-size=1280,1000"],
            )
            assert "error" not in viewer_browser, viewer_browser
            viewer, _ = await connect_page(http, viewer_browser["port"])
            await viewer.call("Page.navigate", {"url": viewer_url})
            await wait_for(
                lambda: viewer.js("window.isConnected"), lambda value: value is True, 30
            )

            async def green_pixels():
                return await viewer.js("""(()=>{const c=document.querySelector('canvas');
                    if(!c?.width)return 0;const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
                    let n=0;for(let i=0;i<d.length;i+=4)if(d[i]===34&&d[i+1]===170&&d[i+2]===102)n++;return n})()""")

            await wait_for(green_pixels, lambda value: value > 100_000, 30)
            (tmp_path / "worker-novnc.png").write_bytes(
                base64.b64decode((await viewer.call("Page.captureScreenshot"))["data"])
            )
            geometry = await page.js("""(()=>{const r=submit.getBoundingClientRect();return {
                x:screenX+r.x+r.width/2,
                y:screenY+outerHeight-innerHeight+r.y+r.height/2}})()""")
            rect = await viewer.js("""(()=>{const c=document.querySelector('canvas'),r=c.getBoundingClientRect();
                return {x:r.x,y:r.y,width:r.width,height:r.height,w:c.width,h:c.height}})()""")
            point = {
                "x": rect["x"] + geometry["x"] * rect["width"] / rect["w"],
                "y": rect["y"] + geometry["y"] * rect["height"] / rect["h"],
            }
            await viewer.call(
                "Input.dispatchMouseEvent", {"type": "mouseMoved", **point}
            )
            for phase in ("mousePressed", "mouseReleased"):
                await viewer.call(
                    "Input.dispatchMouseEvent",
                    {
                        "type": phase,
                        **point,
                        "button": "left",
                        "buttons": 1 if phase == "mousePressed" else 0,
                        "clickCount": 1,
                    },
                )
            await viewer.js(
                "rfb.sendKey(0x61,'KeyA');rfb.clipboardPasteFrom('UNGUARDED_RFB_WRITE')"
            )
            await wait_for(
                lambda: asyncio.sleep(0, result=forwarded_types.copy()),
                lambda types: 5 in types and 4 in types and 6 in types,
            )
            # A server observation after the real outbound input confirms no
            # trusted page handler ran. The browser remains under AI ownership.
            assert remote_site[1] == []
            assert await page.js("document.querySelector('#name').value") == ""
            assert (await worker.state())["state"] == "ai"
            selection = await asyncio.create_subprocess_exec(
                "xclip",
                "-selection",
                "clipboard",
                "-out",
                env={**os.environ, "DISPLAY": worker.display.display},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            actual_clipboard, _ = await asyncio.wait_for(selection.communicate(), 5)
            assert (
                selection.returncode == 0
                and actual_clipboard == b"OWNED_CLIPBOARD_CANARY"
            )

            held = (await host({"kind": "take", **epochs(await worker.state())}))[
                "session"
            ]
            await wait_for(
                lambda: viewer.js("window.isConnected"), lambda value: value is False
            )
            with pytest.raises(ControlError, match="browser_control_held_by_user"):
                await worker.agent(
                    {"kind": "navigate", "url": remote_site[0], **epochs(held)}
                )
            # The original RFB channel cannot carry a stale target into a new epoch.
            async with http.get(
                origin + "/window-stream",
                headers={
                    **headers,
                    "X-ADB-Browser-Context": quote(json.dumps(context)),
                },
            ) as response:
                assert response.status == 409
                assert (await response.json())["error"] == "stale_browser_operation"
            await wait_for(
                lambda: asyncio.sleep(
                    0,
                    result=all(
                        process.poll() is not None for process in first_processes
                    ),
                ),
                bool,
            )
            stream = await get_stream()
            await viewer.call("Page.reload")
            await wait_for(
                lambda: viewer.js("window.isConnected"), lambda value: value is True, 30
            )
            await wait_for(green_pixels, lambda value: value > 100_000, 30)
            # Both image and streamed-canvas viewers use the public gesture
            # mapper. Only its checked host callback can write to Chrome.
            await viewer.js("""(async()=>{
                const {InputSurface}=await import('/input-surface.js');
                const canvas=document.querySelector('canvas');canvas.tabIndex=0;
                rfb.viewOnly=true;rfb.focusOnClick=false;
                // Match the shared consumer: noVNC's legacy mousedown capture
                // also runs in viewOnly mode and can cover later pointer input.
                canvas.addEventListener('mousedown',e=>e.stopImmediatePropagation(),true);
                window.viewerPointerEvents=[];
                for(const kind of ['pointerdown','pointermove','pointerup','pointercancel'])
                    canvas.addEventListener(kind,e=>viewerPointerEvents.push({
                        kind,id:e.pointerId,pointerType:e.pointerType,isPrimary:e.isPrimary,
                        buttons:e.buttons,x:e.clientX,y:e.clientY}),true);
                window.surface=new InputSurface(canvas,input=>fetch('/input',{
                    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(input)}));
                surface.resize(canvas.width,canvas.height);
            })()""")
            rect = await viewer.js("""(()=>{const c=document.querySelector('canvas'),r=c.getBoundingClientRect();
                return {x:r.x,y:r.y,width:r.width,height:r.height,w:c.width,h:c.height}})()""")
            point = {
                "x": rect["x"] + geometry["x"] * rect["width"] / rect["w"],
                "y": rect["y"] + geometry["y"] * rect["height"] / rect["h"],
            }
            await viewer.call(
                "Input.dispatchMouseEvent", {"type": "mouseMoved", **point}
            )
            for phase in ("mousePressed", "mouseReleased"):
                await viewer.call(
                    "Input.dispatchMouseEvent",
                    {
                        "type": phase,
                        **point,
                        "button": "left",
                        "buttons": 1 if phase == "mousePressed" else 0,
                        "clickCount": 1,
                    },
                )
            await wait_for(
                lambda: page.js("document.querySelector('#receipt').textContent"), bool
            )
            assert len(remote_site[1]) == 1 and remote_site[1][0]["trusted"]
            assert remote_site[1][0]["press"] == {"buttons": 1, "trusted": True}

            # A real streamed canvas must move before the viewer releases its
            # pointer. This uses the same checked API, not RFB input or JS pan.
            await host(
                {
                    "kind": "navigate",
                    "url": remote_site[0] + "/native-drag",
                    **epochs(held),
                }
            )
            await wait_for(
                lambda: page.js("Boolean(document.querySelector('#stage'))"), bool
            )
            geometry = await page.js("""(()=>{const r=stage.getBoundingClientRect();return {
                x:r.x+r.width*.85,y:r.y+r.height*.85,
                left:r.x,top:r.y,
                offsetX:screenX+(outerWidth-innerWidth)/2,
                offsetY:screenY+outerHeight-innerHeight-(outerWidth-innerWidth)/2}})()""")
            await viewer.js(
                """(async()=>{
                surface.dispose();
                const {InputSurface}=await import('/input-surface.js');
                const canvas=document.querySelector('canvas');
                canvas.style.touchAction='none';
                window.liveDragPackets=[];
                window.surface=new InputSurface(canvas,async input=>{
                    liveDragPackets.push(input);
                    const response=await fetch('/input',{method:'POST',
                        headers:{'Content-Type':'application/json'},body:JSON.stringify(input)});
                    if(!response.ok)throw new Error('Checked input failed: '+response.status);
                    return response.json();
                },{drag:true,touchDrag:true,liveDrag:true,viewerId:VIEWER});
                surface.resize(canvas.width,canvas.height);
            })()""".replace("VIEWER", json.dumps(viewer_id))
            )
            rect = await viewer.js("""(()=>{const c=document.querySelector('canvas'),r=c.getBoundingClientRect();
                return {x:r.x,y:r.y,width:r.width,height:r.height,w:c.width,h:c.height}})()""")
            start = {
                "x": rect["x"]
                + (geometry["x"] + geometry["offsetX"]) * rect["width"] / rect["w"],
                "y": rect["y"]
                + (geometry["y"] + geometry["offsetY"]) * rect["height"] / rect["h"],
            }
            sample_x = round(geometry["left"] + geometry["offsetX"] + 200 - 40 + 5)
            sample_y = round(geometry["top"] + geometry["offsetY"] + 120 - 20 + 30)
            pixel_expression = f"(()=>{{const c=document.querySelector('canvas');return [...c.getContext('2d').getImageData({sample_x},{sample_y},1,1).data].slice(0,3)}})()"
            before_pixel = await wait_for(
                lambda: viewer.js(pixel_expression), lambda rgb: rgb == [23, 33, 43]
            )

            is_pressed = False
            if touch_drag:
                await viewer.call(
                    "Emulation.setTouchEmulationEnabled",
                    {"enabled": True, "maxTouchPoints": 2},
                )

            async def move_pointer(dx, dy, kind="mouseMoved"):
                nonlocal is_pressed
                if kind in ("mousePressed", "mouseReleased"):
                    is_pressed = kind == "mousePressed"
                point = {
                    "x": start["x"] + dx * rect["width"] / rect["w"],
                    "y": start["y"] + dy * rect["height"] / rect["h"],
                }
                if touch_drag:
                    if kind == "mouseMoved" and not is_pressed:
                        return
                    phase = {
                        "mouseMoved": "touchMove",
                        "mousePressed": "touchStart",
                        "mouseReleased": "touchEnd",
                    }[kind]
                    await viewer.call(
                        "Input.dispatchTouchEvent",
                        {
                            "type": phase,
                            "touchPoints": [{**point, "id": 1}] if is_pressed else [],
                        },
                    )
                    return
                await viewer.call(
                    "Input.dispatchMouseEvent",
                    {
                        "type": kind,
                        **point,
                        "button": "left",
                        "buttons": 1 if is_pressed else 0,
                        **({"clickCount": 1} if kind != "mouseMoved" else {}),
                    },
                )

            await move_pointer(0, 0)
            await move_pointer(0, 0, "mousePressed")
            motion_started = await viewer.js("performance.now()")
            for dx, dy in ((-20, -10), (-40, -20)):
                await move_pointer(dx, dy)
                await wait_for(
                    lambda: page.js("({pan,events:panEvents})"),
                    lambda value, dx=dx, dy=dy: value["pan"] == {"x": dx, "y": dy},
                )
                if dx == -20:
                    packet = await viewer.js("liveDragPackets.at(-1)")
                    assert packet["phase"] == "move"
                    await host(
                        {
                            "kind": "input",
                            "surface": "window",
                            "input": packet,
                            **epochs(held),
                        },
                        expected_error="invalid_browser_drag_sequence",
                    )
                    await host(
                        {
                            "kind": "input",
                            "surface": "window",
                            "input": {
                                **packet,
                                "sequence": packet["sequence"] + 1,
                                "viewerId": "unattached-viewer",
                            },
                            **epochs(held),
                        },
                        expected_error="browser_viewer_not_attached",
                    )
                    if touch_drag:
                        primary = await viewer.js("surface.pointer.id")
                        finger = {
                            "x": start["x"] + dx * rect["width"] / rect["w"],
                            "y": start["y"] + dy * rect["height"] / rect["h"],
                            "id": 1,
                        }
                        await viewer.call(
                            "Input.dispatchTouchEvent",
                            {
                                "type": "touchStart",
                                "touchPoints": [
                                    finger,
                                    {**finger, "x": finger["x"] + 35, "id": 2},
                                ],
                            },
                        )
                        await viewer.call(
                            "Input.dispatchTouchEvent",
                            # Chromium releases the IDs listed on touchEnd.
                            # Release only the secondary finger; the primary
                            # still owns the live remote gesture.
                            {
                                "type": "touchEnd",
                                "touchPoints": [
                                    {**finger, "x": finger["x"] + 35, "id": 2}
                                ],
                            },
                        )
                        assert await viewer.js("surface.pointer.id") == primary
            during = await page.js("({pan,events:panEvents})")
            assert not any(event["kind"] == "pointerup" for event in during["events"])
            assert during["events"][-1]["buttons"] == 1
            visible_pixel = await wait_for(
                lambda: viewer.js(pixel_expression), lambda rgb: rgb == [102, 187, 153]
            )
            assert visible_pixel != before_pixel
            motion_verified = await viewer.js("performance.now()")
            responsive = (await asyncio.wait_for(host({"kind": "state"}), 2))["session"]
            assert responsive["state"] == "human" and responsive["isController"]
            assert responsive["browserSessionId"] == held["browserSessionId"]
            (tmp_path / "live-drag-before-release.png").write_bytes(
                base64.b64decode((await viewer.call("Page.captureScreenshot"))["data"])
            )
            await move_pointer(-100, -50)
            await move_pointer(-100, -50, "mouseReleased")
            completed = await wait_for(
                lambda: page.js("({pan,events:panEvents})"),
                lambda value: (
                    value["pan"] == {"x": -100, "y": -50}
                    and sum(event["kind"] == "pointerup" for event in value["events"])
                    == 1
                ),
            )
            await wait_for(lambda: viewer.js("surface.gesture === null"), bool)
            assert all(event["trusted"] for event in completed["events"])
            viewer_pointer_events = await viewer.js("viewerPointerEvents")
            assert any(
                event["pointerType"] == ("touch" if touch_drag else "mouse")
                and event["kind"] == "pointerdown"
                for event in viewer_pointer_events
            )

            # Close the real viewer during a second press. Bounded driver
            # cleanup must release its native button and retain human control.
            await move_pointer(0, 0)
            await move_pointer(0, 0, "mousePressed")
            await move_pointer(-30, -15)
            await wait_for(
                lambda: page.js("({pan,events:panEvents})"),
                lambda value: value["pan"] == {"x": -130, "y": -65},
            )
            await viewer.close()
            viewer = None
            stopped = await asyncio.to_thread(
                browser_stop, session_id=viewer_browser["session_id"]
            )
            assert stopped.get("stopped") is True, stopped
            viewer_browser = None
            disconnected = await wait_for(
                lambda: page.js("({pan,events:panEvents})"),
                lambda value: (
                    sum(event["kind"] == "pointerup" for event in value["events"]) == 2
                ),
            )
            assert disconnected["events"][-1]["buttons"] == 0
            await wait_for(
                lambda: asyncio.sleep(0, result=stream.view.running),
                lambda running: not running,
            )
            state = await worker.state(controller)
            assert state["state"] == "human" and state["isController"]
            assert worker.live_drag is None
            assert "profile=isolated" in await page.js("document.cookie")
            assert worker.browser["transport"] == transport and worker.session
            assert state["controlEpoch"] > held["controlEpoch"]
            assert state["targetEpoch"] == held["targetEpoch"]
            # Switching the attached surface cancels a fresh native press.
            # It preserves the same browser/profile and rejects old coordinates.
            await host(
                {
                    "kind": "input",
                    "surface": "window",
                    **epochs(state),
                    "input": {
                        "kind": "drag-stream",
                        "phase": "begin",
                        "sequence": 0,
                        "gestureId": secrets.token_hex(16),
                        "viewerId": viewer_id,
                        "x": geometry["x"] + geometry["offsetX"],
                        "y": geometry["y"] + geometry["offsetY"],
                    },
                }
            )
            changed = (
                await host({"kind": "attach", "viewerId": viewer_id, "surface": "page"})
            )["session"]
            switched = await wait_for(
                lambda: page.js("({pan,events:panEvents})"),
                lambda value: (
                    sum(event["kind"] == "pointerup" for event in value["events"]) == 3
                ),
            )
            assert switched["events"][-1]["buttons"] == 0
            assert changed["state"] == "human" and changed["isController"]
            assert changed["controlEpoch"] > state["controlEpoch"]
            assert changed["browserSessionId"] == state["browserSessionId"]
            assert (
                changed["profileId"] == state["profileId"] and worker.live_drag is None
            )
            # The normal Stop intent drains held input without becoming stale
            # on that same cancellation. AI cannot stop a human-held browser.
            attached = (
                await host(
                    {"kind": "attach", "viewerId": viewer_id, "surface": "window"}
                )
            )["session"]
            await host(
                {
                    "kind": "input",
                    "surface": "window",
                    **epochs(attached),
                    "input": {
                        "kind": "drag-stream",
                        "phase": "begin",
                        "sequence": 0,
                        "gestureId": secrets.token_hex(16),
                        "viewerId": viewer_id,
                        "x": geometry["x"] + geometry["offsetX"],
                        "y": geometry["y"] + geometry["offsetY"],
                    },
                }
            )
            with pytest.raises(ControlError, match="browser_control_held_by_user"):
                await worker.agent({"kind": "stop", **epochs(attached)})
            assert worker.live_drag and not worker.live_drag["gesture"].task.done()
            explicit_stop = (await host({"kind": "stop", **epochs(attached)}))[
                "session"
            ]
            assert explicit_stop["state"] == "stopped" and worker.browser is None
            assert explicit_stop["profileId"] == attached["profileId"]
            assert (worker.root / "chrome").is_dir() and worker.live_drag is None
            (tmp_path / "live-drag.json").write_text(
                json.dumps(
                    {
                        "transport": transport,
                        "pointerType": "touch" if touch_drag else "mouse",
                        "viewerPointerEvents": viewer_pointer_events,
                        "secondaryTouchIgnored": touch_drag,
                        "nativeMotionBeforeRelease": during,
                        "decodedPixelBefore": before_pixel,
                        "decodedPixelWhileHeld": visible_pixel,
                        "motionToVerifiedPixelsUpperBoundMs": round(
                            motion_verified - motion_started, 2
                        ),
                        "statusResponsiveDuringGesture": True,
                        "duplicatePacketAndForeignViewerRejected": True,
                        "completed": completed,
                        "viewerDisconnected": disconnected,
                        "humanLeasePreserved": True,
                        "browserPreserved": True,
                        "surfaceSwitchReleasedInputAndFencedCoordinates": True,
                        "explicitStopDrainedGestureAndPreservedProfile": True,
                    },
                    indent=2,
                )
            )
        except Exception:
            if viewer:
                try:
                    audit = await viewer.js("""(()=>{const c=document.querySelector('canvas'),r=c?.getBoundingClientRect();return {
                        pointerEvents:window.viewerPointerEvents||[],packets:window.liveDragPackets||[],
                        pointer:window.surface?.pointer,
                        canvas:r?{x:r.x,y:r.y,w:r.width,h:r.height}:null,
                        activeElement:document.activeElement?.tagName,
                        captureElements:[...document.querySelectorAll('[id*=capture],[class*=capture]')].map(e=>({id:e.id,tag:e.tagName,class:e.className}))}})()""")
                    (tmp_path / "viewer-input-failure.json").write_text(
                        json.dumps(audit, indent=2)
                    )
                    (tmp_path / "viewer-input-failure.png").write_bytes(
                        base64.b64decode(
                            (await viewer.call("Page.captureScreenshot"))["data"]
                        )
                    )
                except (BrowserViewError, aiohttp.ClientError, ConnectionError):
                    pass
            raise
        finally:
            if clipboard and clipboard.returncode is None:
                clipboard.terminate()
                await clipboard.wait()
            if viewer:
                await viewer.close()
            if viewer_browser and "session_id" in viewer_browser:
                stopped = await asyncio.to_thread(
                    browser_stop, session_id=viewer_browser["session_id"]
                )
                assert stopped.get("stopped") is True, stopped
            if viewer_runner:
                await viewer_runner.cleanup()
            await runner.cleanup()
