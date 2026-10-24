"""Real Chrome/noVNC stream: pixels, hostile raw input, guarded input and reconnect."""

import asyncio
import base64
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote

import aiohttp
import pytest
from aiohttp import web

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.worker import Worker, application
from tests.integration.test_remote_view import connect_page, wait_for

pytest_plugins = ["tests.integration.test_remote_view"]


@pytest.mark.skipif(
    sys.platform != "linux", reason="An isolated X11 display is required"
)
@pytest.mark.parametrize("transport", ["cdp", "extension"])
async def test_authenticated_window_stream_cannot_bypass_input_lease(
    tmp_path, remote_site, transport
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

        async def host(action):
            async with http.post(
                origin + "/invoke",
                headers=headers,
                json={"binding": binding, "controller": controller, "action": action},
            ) as response:
                body = await response.json()
                assert response.status == 200, (response.status, body)
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
            app.add_routes([web.get("/", viewer_html), web.get("/view", proxy)])
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
            await host(
                {
                    "kind": "input",
                    "surface": "window",
                    "input": {"kind": "click", **geometry},
                    **epochs(held),
                }
            )
            await wait_for(
                lambda: page.js("document.querySelector('#receipt').textContent"), bool
            )
            assert len(remote_site[1]) == 1 and remote_site[1][0]["trusted"]
            assert remote_site[1][0]["press"] == {"buttons": 1, "trusted": True}

            await viewer.close()
            viewer = None
            stopped = await asyncio.to_thread(
                browser_stop, session_id=viewer_browser["session_id"]
            )
            assert stopped.get("stopped") is True, stopped
            viewer_browser = None
            await wait_for(
                lambda: asyncio.sleep(0, result=stream.view.running),
                lambda running: not running,
            )
            state = await worker.state(controller)
            assert state["state"] == "human" and state["isController"]
            assert "profile=isolated" in await page.js("document.cookie")
            assert worker.browser["transport"] == transport and worker.session
        finally:
            if clipboard and clipboard.returncode is None:
                clipboard.terminate()
                await clipboard.wait()
            if viewer:
                await viewer.close()
            if viewer_browser:
                stopped = await asyncio.to_thread(
                    browser_stop, session_id=viewer_browser["session_id"]
                )
                assert stopped.get("stopped") is True, stopped
            if viewer_runner:
                await viewer_runner.cleanup()
            await runner.cleanup()
