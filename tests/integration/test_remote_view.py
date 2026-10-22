"""Real Chrome workflows for the shared page viewer, with no model mocks."""

import asyncio
import base64
import json
import sys
import traceback
import urllib.error
import urllib.request
from importlib.resources import files
from io import BytesIO

import aiohttp
import pytest
from aiohttp import web
from PIL import Image

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core._transport import ProtocolException
from ai_dev_browser.core.connection import connect_browser, get_active_tab
from ai_dev_browser.core.navigation import page_goto
from ai_dev_browser.core.port import (
    _open_chrome_http,
    _query_chrome_cmdline,
    _query_chrome_guid,
    _query_chrome_version,
    is_port_in_use,
)
from ai_dev_browser.remote.cdp import CDP
from ai_dev_browser.remote.page import PageView


async def wait_for(operation, predicate, timeout=15):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        value = await operation()
        if predicate(value):
            return value
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"Browser state did not arrive: {value!r}")
        await asyncio.sleep(0.05)


@pytest.fixture
async def remote_site():
    receipts = []
    target = None
    view = PageView()
    lock = asyncio.Lock()
    sockets = set()
    fixture = """<!doctype html><meta charset="utf-8">
    <style>body{margin:0;background:#eee}input,button{display:block;margin:24px;width:220px;height:40px}</style>
    <input id="name"><button id="submit">Submit once</button><pre id="receipt"></pre>
    <p id="phrase" style="margin:24px;font:20px monospace;white-space:pre">alpha CANONICAL_REVIEW_PHRASE omega</p>
    <textarea id="notes" style="margin:24px;width:380px;height:80px"></textarea>
    <button id="recordNotes">Submit review</button>
    <script>document.cookie='profile=isolated; SameSite=Lax';
    recordNotes.onclick=event=>fetch('/receipt',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({notes:notes.value,trusted:event.isTrusted})});
    let press=null;submit.onmousedown=event=>{press={buttons:event.buttons,trusted:event.isTrusted}};
    submit.onclick=async event=>{
      const response=await fetch('/receipt',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:document.querySelector('#name').value,trusted:event.isTrusted,press})});
      document.querySelector('#receipt').textContent=JSON.stringify(await response.json());
    };</script>"""

    async def page(request):
        return web.Response(text=fixture, content_type="text/html")

    async def receipt(request):
        value = await request.json()
        value["cookie"] = request.cookies.get("profile")
        value["sequence"] = len(receipts) + 1
        receipts.append(value)
        return web.json_response(value)

    async def native_drag_page(request):
        return web.Response(
            text="""<!doctype html><meta charset="utf-8">
            <style>body{margin:24px}canvas{display:block;touch-action:none;background:#17212b}</style>
            <canvas id="stage" width="600" height="300"></canvas>
            <script>
            const ctx=stage.getContext('2d');
            window.pan={x:0,y:0};window.panEvents=[];
            let gesture=null;
            function draw(){ctx.clearRect(0,0,600,300);ctx.fillStyle='#66bb99';ctx.fillRect(200+pan.x,120+pan.y,100,60)}
            draw();
            for(const kind of ['pointerdown','pointermove','pointerup'])stage.addEventListener(kind,e=>{
              panEvents.push({kind:e.type,trusted:e.isTrusted,buttons:e.buttons});
              if(e.type==='pointerdown'){gesture={x:e.clientX,y:e.clientY,ox:pan.x,oy:pan.y,armed:false};return}
              if(e.type==='pointerup'){gesture=null;return}
              if(!gesture)return;
              const dx=e.clientX-gesture.x,dy=e.clientY-gesture.y;
              // Like a canvas editor, cross the activation threshold before panning.
              if(!gesture.armed){if(Math.hypot(dx,dy)>8)gesture.armed=true;return}
              pan.x=gesture.ox+dx;pan.y=gesture.oy+dy;draw();
            });
            </script>""",
            content_type="text/html",
        )

    async def viewer(request):
        return web.Response(
            text="""<!doctype html><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <img id="screen" tabindex="0" style="display:block;width:240px;border:0;touch-action:none">
        <input id="entry"><button id="insert">Insert text</button>
        <script type="module">
        import {PageSurface} from '/page-view.js';
        const ws=new WebSocket(location.origin.replace('http','ws')+'/view');
        const surface=new PageSurface(document.querySelector('#screen'), value=>ws.send(JSON.stringify(value)),
          {drag:new URLSearchParams(location.search).has('drag'),
           touchDrag:new URLSearchParams(location.search).has('touch-drag')});
        ws.onopen=()=>ws.send(JSON.stringify({token:'fixture-controller'}));
        ws.onmessage=event=>{const value=JSON.parse(event.data);surface.frame(value);};
        document.querySelector('#insert').onclick=()=>{
          surface.send({kind:'text',text:document.querySelector('#entry').value});
          document.querySelector('#entry').value='';
        };
        window.disconnect=()=>ws.close();window.surface=surface;
        </script>""",
            content_type="text/html",
        )

    async def asset(request):
        return web.Response(
            text=files("ai_dev_browser.remote").joinpath("page_view.js").read_text(),
            content_type="text/javascript",
        )

    async def socket(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        first = await ws.receive_json()
        if first != {"token": "fixture-controller"}:
            await ws.close(code=1008)
            return ws
        sockets.add(ws)

        async def frames():
            while not ws.closed:
                async with lock:
                    data = await view.capture(target)
                await ws.send_json({"data": data, "width": 480, "height": 850})
                await asyncio.sleep(0.1)

        pending = asyncio.create_task(frames())

        def frame_completed(task):
            if not task.cancelled() and (error := task.exception()):
                # This owned fixture must expose a producer failure instead of
                # reporting only an unrelated image-load timeout in the viewer.
                traceback.print_exception(error)

        pending.add_done_callback(frame_completed)
        try:
            async for message in ws:
                if message.type != aiohttp.WSMsgType.TEXT:
                    break
                async with lock:
                    await view.input(
                        target, json.loads(message.data), width=480, height=850
                    )
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            sockets.discard(ws)
        return ws

    app = web.Application()
    app.add_routes(
        [
            web.get("/", page),
            web.get("/native-drag", native_drag_page),
            web.post("/receipt", receipt),
            web.get("/viewer", viewer),
            web.get("/view", socket),
            web.get("/page-view.js", asset),
        ]
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"

    def bind(page):
        nonlocal target
        target = page

    try:
        yield url, receipts, bind, view
    finally:
        await asyncio.gather(*(ws.close() for ws in tuple(sockets)))
        await runner.cleanup()


async def connect_page(http, port, target_id=None):
    async with http.get(f"http://127.0.0.1:{port}/json/list") as response:
        targets = await response.json()
    target = next(
        t
        for t in targets
        if t["type"] == "page" and (target_id is None or t["id"] == target_id)
    )
    cdp = CDP(await http.ws_connect(target["webSocketDebuggerUrl"]))
    await cdp.call("Page.enable")
    await cdp.call("Page.bringToFront")
    return cdp, target["id"]


async def navigate_owned_browser(browser, url, evidence_dir=None, settle_timeout=15):
    # Reuse adb's selected-page preparation and awaited navigation. The host
    # chooses its owned target explicitly; view adapters do not navigate/retry.
    controller = await connect_browser(
        port=browser["port"], session_id=browser["session_id"]
    )
    aborted = None
    observed = None
    result = None
    try:
        tab = await get_active_tab(controller)
        assert str(tab._target.target_id) == browser["automation_target_id"]
        try:
            result = await page_goto(tab, url)
        except ProtocolException as exc:
            if "net::ERR_ABORTED" not in str(exc):
                raise
            aborted = str(exc)

            async def state():
                nonlocal observed
                try:
                    observed = await tab.evaluate(
                        "({url:location.href,ready:document.readyState})",
                        return_by_value=True,
                    )
                    return observed
                except ProtocolException as reading:
                    if not any(
                        text in str(reading)
                        for text in (
                            "Cannot find context",
                            "Execution context was destroyed",
                        )
                    ):
                        raise
                    return {"url": "", "ready": "changing"}

            # Observe the one navigation already dispatched. A competing
            # startup navigation may cancel its protocol reply while the same
            # destination commits. Never issue another navigate or replay input.
            observed = await wait_for(
                state,
                lambda value: value["url"].rstrip("/") == url.rstrip("/")
                and value["ready"] in ("interactive", "complete"),
                timeout=settle_timeout,
            )
            result = {"url": observed["url"], "ready": True}
        assert result["ready"] and result["url"].rstrip("/") == url.rstrip("/"), result
        result["startup_navigation_aborted"] = aborted is not None
        return result
    finally:
        if evidence_dir is not None:
            (evidence_dir / "startup-navigation-evidence.json").write_text(
                json.dumps(
                    {
                        "helper_navigation_count": 1,
                        "error": aborted,
                        "observed": observed,
                        "result": result,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        await controller.close()


async def test_owned_browser_identity_and_close_with_outbound_proxy(
    remote_site, monkeypatch, tmp_path
):
    """An outbound proxy must not intercept owned Chrome's local control path."""
    requests = []

    async def reject(request):
        requests.append(request.raw_path)
        return web.Response(status=502, text="fixture proxy rejects control")

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", reject)
    runner = web.AppRunner(app)
    await runner.setup()
    proxy = web.TCPSite(runner, "127.0.0.1", 0)
    await proxy.start()
    proxy_url = f"http://127.0.0.1:{proxy._server.sockets[0].getsockname()[1]}"
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(name, proxy_url)
    for name in ("NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    # urllib caches its default opener; isolate the fixture from earlier tests.
    monkeypatch.setattr(urllib.request, "_opener", None)
    browser = None
    try:
        # Prove the proxy is active for remote hosts, then watch for any local
        # HTTP or WebSocket control request escaping to it during the journey.
        with pytest.raises(urllib.error.HTTPError) as rejected:
            await asyncio.to_thread(
                _open_chrome_http,
                "http://proxy-check.invalid/json/version",
                "proxy-check.invalid",
                2,
            )
        assert rejected.value.code == 502
        assert requests == ["http://proxy-check.invalid/json/version"]
        requests.clear()

        browser = await asyncio.to_thread(
            browser_start,
            headless=True,
            stealth=False,
            temp=True,
            silent_stderr=True,
            extra_args=["--no-sandbox"] if sys.platform == "linux" else [],
        )
        assert "error" not in browser, browser
        assert browser["connected"] is True
        port = browser["port"]
        guid = await asyncio.to_thread(_query_chrome_guid, port)
        assert browser["session_id"] == "cdp-" + guid
        version = await asyncio.to_thread(_query_chrome_version, port)
        assert version["Browser"] == browser["browser_version"]
        args = await asyncio.to_thread(_query_chrome_cmdline, port)
        assert f"--remote-debugging-port={port}" in args

        async with aiohttp.ClientSession() as http:
            page, target_id = await connect_page(http, port)
            try:
                assert target_id == browser["automation_target_id"]
                await page.call("Page.navigate", {"url": remote_site[0]})
                await wait_for(lambda: page.js("document.cookie"), bool)
                assert "profile=isolated" in await page.js("document.cookie")
            finally:
                await page.close()
        controller = await connect_browser(port=port, session_id=browser["session_id"])
        try:
            current = await get_active_tab(controller)
            assert str(current._target.target_id) == browser["automation_target_id"]
            assert "profile=isolated" in await current.evaluate(
                "document.cookie", return_by_value=True
            )
        finally:
            await controller.close()
        stopped = await asyncio.to_thread(
            browser_stop, session_id=browser["session_id"]
        )
        assert stopped["stopped"] is True and stopped["count"] == 1, stopped
        assert stopped["browsers"][0]["pid"] == browser["pid"]
        # Windows can finish child-process teardown after the stop result; wait
        # for the owned debug listener to disappear before asserting cleanup.
        await wait_for(
            lambda: asyncio.to_thread(is_port_in_use, port=port),
            lambda listening: not listening,
        )
        browser = None
        # Chromium on Linux can legitimately inherit the outbound proxy for
        # its own background website requests. Only local control is direct.
        local_control = [
            request
            for request in requests
            if request.startswith(("http://127.0.0.1:", "127.0.0.1:"))
        ]
        assert local_control == [], local_control
        (tmp_path / "proxy-identity-evidence.json").write_text(
            json.dumps(
                {
                    "browser_version": version["Browser"],
                    "same_automation_target": True,
                    "local_control_proxy_requests": len(local_control),
                    "outbound_proxy_requests": len(requests),
                    "owned_close": stopped,
                }
            ),
            encoding="utf-8",
        )
    finally:
        if browser and browser.get("session_id"):
            await asyncio.to_thread(browser_stop, session_id=browser["session_id"])
        await runner.cleanup()


@pytest.mark.parametrize("headless", [True, False])
async def test_remote_surface_submission_and_same_profile_reconnect(
    remote_site, tmp_path, headless
):
    """Real scenario: View -> scaled trusted input -> Unicode receipt -> reconnect.

    The viewer and target are separate real Chrome processes. The public JS
    surface maps local pointer/keyboard input to the target's existing tab.
    Only a single server-confirmed submission counts as success.
    """
    url, receipts, bind, view = remote_site
    browsers, connections = [], []
    async with aiohttp.ClientSession() as http:
        try:
            for mode in (headless, True):
                result = await asyncio.to_thread(
                    browser_start,
                    headless=mode,
                    temp=True,
                    # Chrome's GPU/Crashpad output must not fill an unread pipe
                    # while these two real browsers stream snapshots.
                    silent_stderr=True,
                    # These owned loopback fixtures also run on Ubuntu CI,
                    # where AppArmor prevents Chrome's user-namespace sandbox.
                    # Keep this owned headful fixture painting even when another
                    # desktop window occludes it. User Chrome defaults stay intact.
                    extra_args=[
                        "--window-size=1024,1000",
                        "--window-position=0,0",
                        "--disable-backgrounding-occluded-windows",
                        "--disable-renderer-backgrounding",
                        "--disable-background-timer-throttling",
                        "--disable-features=CalculateNativeWinOcclusion",
                    ]
                    + (["--no-sandbox"] if sys.platform == "linux" else []),
                )
                assert "error" not in result, result
                browsers.append(result)
            await navigate_owned_browser(browsers[0], url)
            target, target_id = await connect_page(
                http, browsers[0]["port"], browsers[0]["automation_target_id"]
            )
            client, _ = await connect_page(
                http, browsers[1]["port"], browsers[1]["automation_target_id"]
            )
            connections.extend((target, client))
            bind(target)
            await client.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": 900, "height": 1000, "deviceScaleFactor": 1, "mobile": False},
            )
            await target.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": 480, "height": 850, "deviceScaleFactor": 1, "mobile": False},
            )
            await wait_for(
                lambda: target.js("!!document.querySelector('#submit')"), bool
            )
            await target.call("Page.bringToFront")
            assert await target.js(
                "new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))"
            )
            # Observe the painted page before streaming it to the real viewer.
            # DOM readiness alone can precede the first headful compositor frame.
            assert await view.capture(target)
            await navigate_owned_browser(browsers[1], url + "/viewer")
            navigation = {"requested_url": url + "/viewer", "core_navigation": True}
            try:
                await wait_for(
                    lambda: client.js(
                        "document.querySelector('#screen')?.naturalWidth"
                    ),
                    bool,
                )
            except Exception:
                diagnostic = await client.js(
                    "({url:location.href,state:document.readyState,title:document.title,body:document.body?.innerText,html:document.documentElement.outerHTML.slice(0,4096)})"
                )
                (tmp_path / "viewer-navigation-evidence.json").write_text(
                    json.dumps({"navigation": navigation, "page": diagnostic}),
                    encoding="utf-8",
                )
                print("Actual viewer navigation:", diagnostic)
                raise
            image = Image.open(BytesIO(base64.b64decode(view.last_frame)))
            assert image.size == (480, 850)
            image.save(tmp_path / "remote-view.jpg")

            # Pointer positions come from the viewer's scaled image.
            box = await client.js(
                "(()=>{const r=document.querySelector('#screen').getBoundingClientRect();return {x:r.x,y:r.y}})()"
            )
            for y in (44,):
                await client.call(
                    "Input.dispatchMouseEvent",
                    {"type": "mouseMoved", "x": box["x"] + 60, "y": box["y"] + y / 2},
                )
                for phase in ("mousePressed", "mouseReleased"):
                    await client.call(
                        "Input.dispatchMouseEvent",
                        {
                            "type": phase,
                            "x": box["x"] + 60,
                            "y": box["y"] + y / 2,
                            "button": "left",
                            "buttons": 1 if phase == "mousePressed" else 0,
                            "clickCount": 1,
                        },
                    )
            await wait_for(
                lambda: target.js("document.activeElement.id"), lambda v: v == "name"
            )
            # The human replaces existing AI text through the actual viewer's
            # keyboard shortcut, rather than appending to it or using page JS.
            await target.call("Input.insertText", {"text": "AI text to replace"})
            for phase in ("keyDown", "keyUp"):
                await client.call(
                    "Input.dispatchKeyEvent",
                    {
                        "type": phase,
                        "key": "a",
                        "code": "KeyA",
                        "windowsVirtualKeyCode": 65,
                        "modifiers": 2,
                    },
                )
            await wait_for(
                lambda: target.js(
                    "(()=>{const e=document.querySelector('#name');return [e.selectionStart,e.selectionEnd,e.value.length]})()"
                ),
                lambda v: (
                    v == [0, len("AI text to replace"), len("AI text to replace")]
                ),
            )
            # Type into the real viewer UI, then use its explicit text control.
            for selector in ("#entry", "#insert"):
                point = await client.js(
                    "(()=>{const r=document.querySelector("
                    + json.dumps(selector)
                    + ").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()"
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
                if selector == "#entry":
                    await wait_for(
                        lambda: client.js("document.activeElement.id"),
                        lambda v: v == "entry",
                    )
                    await client.call("Input.insertText", {"text": "同一会话 ✓"})
                    assert (
                        await client.js("document.querySelector('#entry').value")
                        == "同一会话 ✓"
                    )
            await wait_for(
                lambda: target.js("document.querySelector('#name').value"),
                lambda v: v == "同一会话 ✓",
            )
            await client.call(
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": box["x"] + 60, "y": box["y"] + 106 / 2},
            )
            for phase in ("mousePressed", "mouseReleased"):
                await client.call(
                    "Input.dispatchMouseEvent",
                    {
                        "type": phase,
                        "x": box["x"] + 60,
                        "y": box["y"] + 106 / 2,
                        "button": "left",
                        "buttons": 1 if phase == "mousePressed" else 0,
                        "clickCount": 1,
                    },
                )
            await wait_for(
                lambda: target.js("document.querySelector('#receipt').textContent"),
                lambda v: "sequence" in v,
            )
            assert receipts == [
                {
                    "name": "同一会话 ✓",
                    "trusted": True,
                    "press": {"buttons": 1, "trusted": True},
                    "cookie": "isolated",
                    "sequence": 1,
                }
            ]
            for event in (
                {"kind": "click", "x": None, "y": 10},
                {"kind": "wheel", "x": 10, "y": 10, "dy": "invalid"},
                {"kind": "key", "key": []},
                {"kind": "text", "text": "\x00"},
            ):
                assert not await view.input(target, event, width=480, height=850)
            assert (
                await target.js("document.querySelector('#name').value") == "同一会话 ✓"
            )

            # Closing UI/socket connections preserves Chrome, target and profile.
            await client.js("disconnect()")
            await target.close()
            replacement, current_id = await connect_page(
                http, browsers[0]["port"], target_id
            )
            connections.append(replacement)
            bind(replacement)
            assert current_id == target_id
            assert "同一会话" in await replacement.js(
                "document.querySelector('#receipt').textContent"
            )
            assert "profile=isolated" in await replacement.js("document.cookie")
            await client.call("Page.reload")
            await wait_for(
                lambda: client.js("document.querySelector('#screen')?.naturalWidth"),
                bool,
            )
            await replacement.call("Page.reload")
            await wait_for(
                lambda: replacement.js(
                    "document.readyState==='complete' && !!document.querySelector('#name')"
                ),
                bool,
            )
            await replacement.call("Page.bringToFront")
            assert await replacement.js(
                "new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))"
            )
            # Hand-back requires a fresh observation after navigation. DOM load
            # completion alone does not mean the new frame's hit-test data exists.
            observed = await view.capture(replacement)
            Image.open(BytesIO(base64.b64decode(observed))).save(
                tmp_path / "reconnected-view.jpg"
            )
            await view.input(
                replacement, {"kind": "click", "x": 40, "y": 40}, width=480, height=850
            )
            await wait_for(
                lambda: replacement.js(
                    "({id:document.activeElement.id,focus:document.hasFocus(),state:document.readyState,rect:document.querySelector('#name').getBoundingClientRect().toJSON()})"
                ),
                lambda v: v["id"] == "name",
            )
            await view.input(
                replacement,
                {"kind": "text", "text": "AI continues"},
                width=480,
                height=850,
            )
            assert (
                await replacement.js("document.querySelector('#name').value")
                == "AI continues"
            )
            assert len(receipts) == 1  # No replay on reconnect, reload or hand-back.
        finally:
            await asyncio.gather(
                *(c.close() for c in connections), return_exceptions=True
            )
            for browser in browsers:
                await asyncio.to_thread(browser_stop, port=browser["port"])


async def test_remote_page_real_extension(remote_site, live_extension, tmp_path):
    """Extension -> same tab pixels -> trusted input -> profile cookie -> receipt."""
    url, receipts, _, view = remote_site
    async with aiohttp.ClientSession() as http:
        browser = CDP(
            await http.ws_connect(
                f"http://127.0.0.1:{live_extension.port}/devtools/browser"
            )
        )
        try:
            state = await browser.call("AiDevBrowser.debugState")
        finally:
            await browser.close()
        page = CDP(
            await http.ws_connect(
                f"http://127.0.0.1:{live_extension.port}/devtools/page/{state['mainTabId']}"
            )
        )
        try:
            await page.call("Page.navigate", {"url": url})
            await wait_for(lambda: page.js("!!document.querySelector('#name')"), bool)
            data = await view.capture(page)
            assert Image.open(BytesIO(base64.b64decode(data))).width > 0
            await view.input(
                page, {"kind": "click", "x": 40, "y": 40}, width=480, height=850
            )
            await view.input(
                page, {"kind": "text", "text": "extension 同页"}, width=480, height=850
            )
            await view.input(
                page, {"kind": "click", "x": 40, "y": 110}, width=480, height=850
            )
            await wait_for(
                lambda: page.js("document.querySelector('#receipt').textContent"),
                lambda v: "sequence" in v,
            )
            assert receipts == [
                {
                    "name": "extension 同页",
                    "trusted": True,
                    "press": {"buttons": 1, "trusted": True},
                    "cookie": "isolated",
                    "sequence": 1,
                }
            ]
        finally:
            await page.close()
