"""Real X11 -> x11vnc -> websockify -> noVNC -> Chrome workflow."""

import asyncio
import base64
import json
import os
import shutil
import socket
from io import BytesIO
from pathlib import Path

import aiohttp
import pytest
from PIL import Image

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.remote.vnc import VncView

from .test_remote_view import connect_page, remote_site, wait_for

__all__ = ["remote_site"]


def free_port():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


@pytest.mark.skipif(os.name == "nt", reason="x11vnc is a Linux display adapter")
async def test_vnc_pixels_input_and_owned_cleanup(tmp_path, remote_site):
    """Human opens real noVNC -> same browser frame -> trusted single submission.

    After the view closes, the original Chrome tab/profile still exists. Only
    viewer-owned processes and listeners terminate. No payment site is used.
    """
    assert os.environ.get("DISPLAY"), "Run under an isolated xvfb-run display"
    assert all(shutil.which(tool) for tool in ("x11vnc", "websockify"))
    assert Path("/usr/share/novnc/vnc.html").is_file()
    password_file = tmp_path / "viewer-password"
    password_file.write_text("fixture8")
    password_file.chmod(0o600)
    viewer = VncView(
        display=os.environ["DISPLAY"],
        password_file=password_file,
        vnc_port=free_port(),
        web_port=free_port(),
    )
    browsers, connections = [], []
    url, receipts, _, _ = remote_site
    async with aiohttp.ClientSession() as http:
        try:
            for headless in (False, True):
                result = await asyncio.to_thread(
                    browser_start,
                    headless=headless,
                    temp=True,
                    silent_stderr=True,
                    extra_args=[
                        "--no-sandbox",
                        "--window-position=0,0",
                        "--window-size=1024,768",
                    ],
                )
                assert "error" not in result, result
                browsers.append(result)
            page, original = await connect_page(http, browsers[0]["port"])
            client, _ = await connect_page(http, browsers[1]["port"])
            connections.extend((page, client))
            await client.call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 1280,
                    "height": 1000,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )
            await page.call("Page.navigate", {"url": url})
            await wait_for(
                lambda: page.js(
                    "document.readyState==='complete' && !!document.querySelector('#name')"
                ),
                bool,
            )
            await page.js("document.body.style.background='#22aa66'")
            await asyncio.to_thread(viewer.start)
            await client.call(
                "Page.navigate",
                {
                    "url": f"http://127.0.0.1:{viewer.web_port}/vnc.html?autoconnect=true&password=fixture8&resize=scale"
                },
            )
            await wait_for(
                lambda: client.js(
                    "document.documentElement?.classList.contains('noVNC_connected')"
                ),
                bool,
                30,
            )

            # The RFB connection can finish before its first framebuffer arrives.
            # Wait for visible fixture pixels, preserving the last frame on failure.
            async def painted_pixels():
                frame = await client.js(
                    "document.querySelector('canvas').toDataURL('image/png')"
                )
                image = Image.open(
                    BytesIO(base64.b64decode(frame.split(",", 1)[1]))
                ).convert("RGB")
                image.save(tmp_path / "novnc-live.png")
                return sum(1 for pixel in image.getdata() if pixel == (34, 170, 102))

            await wait_for(painted_pixels, lambda count: count > 100_000, 30)

            # Use the viewer's real pointer handler to press the target button.
            # Native Chrome's toolbar offset is measured from this owned window.
            await page.call("Page.bringToFront")
            location = await page.js(
                "(()=>{const r=document.querySelector('#submit').getBoundingClientRect();return {x:screenX+r.x+r.width/2,y:screenY+outerHeight-innerHeight+r.y+r.height/2}})()"
            )
            geometry = await client.js(
                "(()=>{const c=document.querySelector('canvas'),r=c.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,pixelsX:c.width,pixelsY:c.height}})()"
            )
            point = {
                "x": geometry["x"]
                + location["x"] * geometry["width"] / geometry["pixelsX"],
                "y": geometry["y"]
                + location["y"] * geometry["height"] / geometry["pixelsY"],
            }
            (tmp_path / "viewer-geometry.json").write_text(
                json.dumps(
                    {
                        "location": location,
                        "geometry": geometry,
                        "point": point,
                        "window": await page.js(
                            "({x:screenX,y:screenY,outerHeight,innerHeight,outerWidth,innerWidth,devicePixelRatio})"
                        ),
                    }
                )
            )
            observer = "window.inputEvents=[];for(const type of ['pointerdown','mousedown','mouseup','click'])document.addEventListener(type,e=>inputEvents.push({type,id:e.target.id,buttons:e.buttons,x:e.clientX,y:e.clientY,trusted:e.isTrusted}),true)"
            await client.js(observer)
            await page.js(observer)
            await wait_for(
                lambda: client.js(
                    f"document.elementFromPoint({point['x']},{point['y']})?.tagName"
                ),
                lambda v: v == "CANVAS",
            )
            await client.call(
                "Input.dispatchMouseEvent", {"type": "mouseMoved", **point}
            )
            for phase in ("mousePressed", "mouseReleased"):
                await client.call(
                    "Input.dispatchMouseEvent",
                    {
                        "type": phase,
                        **point,
                        "button": "left",
                        "buttons": 1 if phase == "mousePressed" else 0,
                        "clickCount": 1,
                    },
                )
            try:
                await wait_for(
                    lambda: page.js("document.querySelector('#receipt').textContent"),
                    lambda v: "sequence" in v,
                )
            except AssertionError:
                print(
                    "VNC input diagnostic",
                    json.dumps(
                        {
                            "viewer": await client.js(
                                "({events:inputEvents,viewOnly:document.querySelector('#noVNC_setting_view_only')?.checked,focus:document.hasFocus()})"
                            ),
                            "target": await page.js(
                                "({events:inputEvents,focus:document.hasFocus()})"
                            ),
                        }
                    ),
                    flush=True,
                )
                raise
            assert receipts == [
                {
                    "name": "",
                    "trusted": True,
                    "press": {"buttons": 1, "trusted": True},
                    "cookie": "isolated",
                    "sequence": 1,
                }
            ]
            viewer_pids = [p.pid for p in viewer.processes]
            await asyncio.to_thread(viewer.close)
            assert not viewer.running
            assert all(p.poll() is not None for p in viewer.processes)
            # The reconnect's transport is immediately closed, never Browser.close.
            reconnect, current = await connect_page(http, browsers[0]["port"])
            connections.append(reconnect)
            assert current == original
            assert viewer_pids and "profile=isolated" in await page.js(
                "document.cookie"
            )
        finally:
            await asyncio.to_thread(viewer.close)
            await asyncio.gather(
                *(c.close() for c in connections), return_exceptions=True
            )
            for browser in browsers:
                stopped = await asyncio.to_thread(
                    browser_stop, session_id=browser["session_id"]
                )
                assert stopped.get("stopped") is True, stopped
