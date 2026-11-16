"""Actual native input and snapshots share the original session and barrier."""

import asyncio
import base64
import json
import sys

import aiohttp
from aiohttp import web
import pytest

from ai_dev_browser.core.connection import BrowserClient, get_active_tab
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.navigation import page_goto
from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.session import BrowserSession
from tests.integration.test_remote_view import wait_for


@pytest.fixture
async def owned_operations_browser():
    launched = await asyncio.to_thread(
        browser_start,
        headless=True,
        temp=True,
        stealth=False,
        extra_args=["--no-sandbox"] if sys.platform == "linux" else [],
    )
    assert "error" not in launched, launched
    browser = None
    try:
        from ai_dev_browser.core.connection import connect_browser

        browser = await connect_browser(session_id=launched["session_id"])
        yield browser
    finally:
        if browser:
            await browser.close()
        stopped = await asyncio.to_thread(
            browser_stop, session_id=launched["session_id"]
        )
        assert stopped["stopped"], stopped


async def session_operations_journey(browser, tmp_path):
    receipts = []

    async def form(request):
        return web.Response(
            text="""<!doctype html><meta charset=utf-8><title>Session input</title>
<style>body{font:20px sans-serif;margin:24px;min-height:1800px}input{width:350px;height:48px}</style>
<h1>Original session</h1><label>Request<input id=query></label>
<script>query.oninput=e=>fetch('/receipt',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({value:query.value,trusted:e.isTrusted})});
window.releases=[];addEventListener('keyup',e=>releases.push({key:e.key,trusted:e.isTrusted}));</script>""",
            content_type="text/html",
        )

    async def receipt(request):
        receipts.append(await request.json())
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_get("/", form)
    app.router.add_post("/receipt", receipt)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    origin = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    session = None
    grant = True
    journal = []
    entered, release = asyncio.Event(), asyncio.Event()
    detached = []
    hold = False

    async def current():
        if not grant:
            raise PermissionError("input withdrawn")
        if hold:
            entered.set()
            await release.wait()

    async def custody():
        assert journal in ([], ["Shift"])

    async def frame_read(target, frame):
        assert target == session.target_id and frame["origin"] == origin
        return current

    try:
        await page_goto(await get_active_tab(browser), origin)
        async with aiohttp.ClientSession() as http:
            session = BrowserSession(browser, http)
            await session.state(before_effect=current)
            await session.control.take("original-human", before_effect=current)
            page = await session._connect_page()
            epoch, target_epoch = session.control.epoch, session.control.target_epoch
            identity = session.target_id, page, session.control.snapshot()

            async def packet(operation):
                return await session.page_operation(
                    "original-viewer",
                    "original-human",
                    epoch,
                    target_epoch,
                    operation,
                    before_effect=current,
                )

            async def type_and_hold(commands):
                document = await commands.call("DOM.getDocument")
                node = await commands.call(
                    "DOM.querySelector",
                    {
                        "nodeId": document["root"]["nodeId"],
                        "selector": "#query",
                    },
                )
                await commands.call("DOM.focus", {"nodeId": node["nodeId"]})
                await commands.call(
                    "Input.insertText",
                    {"text": "\u4e2d\u6587 \U0001f469\u200d\U0001f4bb"},
                )
                journal.append("Shift")
                await commands.call(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "rawKeyDown",
                        "key": "Shift",
                        "code": "ShiftLeft",
                        "windowsVirtualKeyCode": 16,
                        "modifiers": 8,
                    },
                )

            await packet(type_and_hold)
            await wait_for(
                lambda: page.js("document.querySelector('#query').value"),
                lambda value: value == "\u4e2d\u6587 \U0001f469\u200d\U0001f4bb",
            )
            await wait_for(
                lambda: asyncio.sleep(0, result=len(receipts)), lambda n: n == 1
            )
            assert receipts == [
                {"value": "\u4e2d\u6587 \U0001f469\u200d\U0001f4bb", "trusted": True}
            ]
            grant = False

            async def release_key(commands):
                assert journal == ["Shift"]
                await commands.call(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "key": "Shift",
                        "code": "ShiftLeft",
                        "windowsVirtualKeyCode": 16,
                        "modifiers": 0,
                    },
                )
                journal.clear()

            await session.cleanup_input(
                "original-viewer", "original-human", release_key, before_cleanup=custody
            )
            assert await page.js("window.releases") == [
                {"key": "Shift", "trusted": True}
            ]
            grant = True

            async def end_while_command_waits(commands):
                nonlocal hold
                hold = True
                detached.append(
                    asyncio.create_task(
                        commands.call(
                            "Input.insertText",
                            {"text": "MUST_NOT_ESCAPE_BARRIER"},
                        )
                    )
                )
                await asyncio.wait_for(entered.wait(), 5)

            await packet(end_while_command_waits)
            assert not session.control._operations.locked()
            hold = False
            release.set()
            with pytest.raises(ControlError, match="^browser_input_context_closed$"):
                await asyncio.wait_for(detached[0], 5)
            assert (
                await page.js("document.querySelector('#query').value")
                == "\u4e2d\u6587 \U0001f469\u200d\U0001f4bb"
            )
            assert len(receipts) == 1
            snapshot = await session.diagnostics(
                epoch, target_epoch, before_read=current, authorize_frame=frame_read
            )
            assert (
                snapshot["screenshot"]["fullPage"]
                and snapshot["screenshot"]["cssHeight"] >= 1800
            )
            assert "Original session" in json.dumps(snapshot["accessibility"])
            assert (
                session.target_id,
                session._page,
                session.control.snapshot(),
            ) == identity
            (tmp_path / "session-operations.png").write_bytes(
                base64.b64decode(snapshot["screenshot"]["data"])
            )
            (tmp_path / "session-operations.json").write_text(
                json.dumps(
                    {
                        "transport": getattr(browser, "transport", None) or "cdp",
                        "sameSessionPageAndHumanLease": True,
                        "trustedUnicodeInput": receipts,
                        "cleanupAfterInputGrantWithdrawal": True,
                        "lateCommandRefused": True,
                        "fullPageDiagnostics": True,
                        "syntheticHostGrants": True,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
    finally:
        release.set()
        if detached:
            await asyncio.gather(*detached, return_exceptions=True)
        if session:
            await session.close()
        await runner.cleanup()


async def test_owned_session_input_cleanup_diagnostics_and_command_lifetime(
    owned_operations_browser, tmp_path
):
    await session_operations_journey(owned_operations_browser, tmp_path)


async def test_extension_session_input_cleanup_diagnostics_and_command_lifetime(
    live_extension, tmp_path
):
    client = await BrowserClient.connect(
        "127.0.0.1",
        live_extension.port,
        ws_url=f"ws://127.0.0.1:{live_extension.port}/devtools/browser",
    )
    client.transport = "extension"
    client._automation_target_id = str(
        live_extension.bridge.identity["automation_target_id"]
    )
    try:
        await session_operations_journey(client, tmp_path)
    finally:
        await client.close()
