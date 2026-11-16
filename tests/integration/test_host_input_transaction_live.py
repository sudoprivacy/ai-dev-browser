"""Actual owned Chrome input/cleanup; original host custody/grants are fixtures."""

import asyncio
import json
import os
import sys

import aiohttp
from aiohttp import web
import pytest

from ai_dev_browser.core import _session, registry
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, get_active_tab
from ai_dev_browser.core.navigation import page_goto
from ai_dev_browser.remote.session import BrowserSession

CHROME = os.environ.get("AI_DEV_BROWSER_CHROME")
pytestmark = pytest.mark.skipif(not CHROME, reason="Explicit owned Chrome executable")


async def test_original_chrome_unicode_and_held_key_cleanup_after_grant_withdrawal(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(_session, "_DIR", tmp_path / "sessions")
    monkeypatch.setattr(registry, "_REGISTRY_DIR", tmp_path / "instances")
    released, observations = asyncio.Event(), []
    application = web.Application()

    async def form(request):
        return web.Response(
            text="""<!doctype html><meta charset="utf-8">
<input id="original" style="position:absolute;left:12px;top:12px;width:300px;height:50px">
<script>addEventListener('keyup',e=>fetch('/released',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:e.key,code:e.code,trusted:e.isTrusted,value:original.value})}));</script>""",
            content_type="text/html",
        )

    async def release_receipt(request):
        observations.append(await request.json())
        released.set()
        return web.json_response({"ok": True})

    application.router.add_get("/", form)
    application.router.add_post("/released", release_receipt)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    record, browser, session = None, None, None
    grant, journal = {"input": True}, {"writer": True, "held": []}

    async def current():
        if not grant["input"]:
            raise PermissionError("original input grant withdrawn")

    async def owns_original():
        if not journal["writer"]:
            raise PermissionError("original journal custody withdrawn")

    try:
        record = await asyncio.to_thread(
            browser_start,
            chrome_path=CHROME,
            headless=True,
            stealth=False,
            profile=str(tmp_path / "original-profile"),
            extra_args=["--disable-gpu", "--no-first-run"]
            + (["--no-sandbox"] if sys.platform == "linux" else []),
        )
        assert "error" not in record, record
        browser = await connect_browser(session_id=record["session_id"])
        await page_goto(await get_active_tab(browser), url=f"http://127.0.0.1:{port}/")
        async with aiohttp.ClientSession() as http:
            session = BrowserSession(browser, http)
            await session.control.take("original-human", before_effect=current)
            epoch, target = session.control.epoch, session.control.target_epoch

            async def original_packet(commands):
                await commands.call("Page.bringToFront")
                await commands.call(
                    "Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 30, "y": 30}
                )
                await commands.call(
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mousePressed",
                        "x": 30,
                        "y": 30,
                        "button": "left",
                        "buttons": 1,
                        "clickCount": 1,
                    },
                )
                await commands.call(
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mouseReleased",
                        "x": 30,
                        "y": 30,
                        "button": "left",
                        "buttons": 0,
                        "clickCount": 1,
                    },
                )
                await commands.call(
                    "Input.insertText", {"text": "中文 input retained 👩‍💻"}
                )
                journal["held"].append("ShiftLeft")
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

            await session.page_operation(
                "original-viewer",
                "original-human",
                epoch,
                target,
                original_packet,
                before_effect=current,
            )
            assert journal["held"] == ["ShiftLeft"]
            grant["input"] = False

            async def original_release(commands):
                assert journal["held"] == ["ShiftLeft"]
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
                journal["held"].clear()

            await session.cleanup_input(
                "original-viewer",
                "original-human",
                original_release,
                before_cleanup=owns_original,
            )
            async with asyncio.timeout(10):
                await released.wait()
            assert observations == [
                {
                    "key": "Shift",
                    "code": "ShiftLeft",
                    "trusted": True,
                    "value": "中文 input retained 👩‍💻",
                }
            ]
            assert journal["held"] == [] and not session._host_input.scopes
            assert (
                session.control.state == "human"
                and session.control.controller == "original-human"
            )
            assert _session.same_process(_session.read(record["session_id"]))
            # Original host lifecycle already owns this exact input barrier.
            async with asyncio.timeout(10):
                await session.control.run(
                    "original-human",
                    epoch,
                    target,
                    session.close,
                    before_effect=owns_original,
                )
            (tmp_path / "actual-host-input-observation.json").write_text(
                json.dumps(
                    {
                        "nativeSession": record["session_id"],
                        "released": observations,
                        "originalInputGrantWithdrawnBeforeCleanup": True,
                        "originalHostJournalCustodyStillPresent": True,
                        "sameControlEpochAndTarget": [epoch, target],
                        "sdkDisconnectPreservesNativeUntilOriginalExplicitStop": _session.same_process(
                            _session.read(record["session_id"])
                        ),
                        "noMossworkDefaultUiOrProductionGrantClaim": True,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
    finally:
        if session is not None:
            await session.close()
        if browser is not None:
            await browser.close()
        if record is not None and "session_id" in record:
            outcome = await asyncio.to_thread(
                browser_stop, session_id=record["session_id"]
            )
            assert outcome.get("stopped") is True
        await runner.cleanup()
