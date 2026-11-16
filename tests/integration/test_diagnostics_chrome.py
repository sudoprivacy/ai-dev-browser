"""Real same-session full-page diagnostics; host grants and sites are fixtures."""

import asyncio
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile

import aiohttp
from aiohttp import web
import pytest
from PIL import Image

from ai_dev_browser.core import _session
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser
from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.session import BrowserSession

pytestmark = pytest.mark.skipif(
    not os.environ.get("AI_DEV_BROWSER_CHROME"),
    reason="Explicit owned Chrome diagnostics qualification",
)


async def test_real_full_page_child_source_grant_and_withdrawn_screenshot_reply(
    tmp_path, monkeypatch
):
    child_app = web.Application()
    child_app.router.add_get(
        "/",
        lambda _: web.Response(
            text="<title>Child source</title><p>Original child source</p>",
            content_type="text/html",
        ),
    )
    child_runner = web.AppRunner(child_app)
    await child_runner.setup()
    child_site = web.TCPSite(child_runner, "127.0.0.1", 0)
    await child_site.start()
    child_origin = f"http://127.0.0.1:{child_site._server.sockets[0].getsockname()[1]}"
    app = web.Application()
    app.router.add_get(
        "/",
        lambda _: web.Response(
            text=f"""<!doctype html><meta charset="utf-8"><title>Original private diagnostic</title>
    <style>html,body{{margin:0;width:100%;height:2500px;background:rgb(240,255,240)}}
    #bottom{{position:absolute;left:0;top:2380px;width:100%;height:120px;background:rgb(180,20,180)}}
    iframe{{position:absolute;top:180px;left:0;width:400px;height:100px}}</style>
    <label>Original diagnostic<input value="diagnostic-original"></label>
    <iframe src="{child_origin}/" onload="window.childReady=true"></iframe>
    <div id="bottom">Original content below the viewport</div>""",
            content_type="text/html",
        ),
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    origin = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    output = Path(os.environ.get("AI_DEV_BROWSER_DIAGNOSTIC_OUTPUT", tmp_path))
    output.mkdir(parents=True, exist_ok=True)
    client = launched = sdk = None
    permit = {"child": False, "read": True}
    requests, methods = [], []
    hold = {"enabled": False}
    entered, release = asyncio.Event(), asyncio.Event()

    async def current():
        if not permit["read"]:
            raise PermissionError("original diagnostic read withdrawn")

    async def frame_grant(target, facts):
        assert target == sdk.target_id and facts["id"] and facts["loaderId"]
        assert facts["origin"] in {origin, child_origin}
        requests.append(copy.deepcopy(facts))
        if facts["origin"] == child_origin and not permit["child"]:
            raise PermissionError("original child source not granted")
        return current  # Explicit same-principal full DOM/AX/pixels/source/DLP fixture.

    with tempfile.TemporaryDirectory(prefix="adb-diag-private-") as private:
        try:
            monkeypatch.setattr(_session, "_DIR", Path(private) / "sessions")
            launched = await asyncio.to_thread(
                browser_start,
                headless=True,
                temp=True,
                stealth=False,
                transport="cdp",
                url=origin + "/",
                chrome_path=os.environ["AI_DEV_BROWSER_CHROME"],
                silent_stderr=True,
                extra_args=["--no-sandbox"] if sys.platform == "linux" else [],
            )
            assert "error" not in launched, {"error_code": launched.get("error_code")}
            client = await connect_browser(session_id=launched["session_id"])
            async with aiohttp.ClientSession() as http:
                sdk = BrowserSession(client, http)
                await sdk.state(before_effect=current)
                page = await sdk._connect_page()
                async with asyncio.timeout(10):
                    while not await page.js("window.childReady===true"):
                        await asyncio.sleep(0.02)
                await sdk.take(
                    "original-human",
                    sdk.control.epoch,
                    sdk.control.target_epoch,
                    before_effect=current,
                )
                epoch, target_epoch = sdk.control.epoch, sdk.control.target_epoch
                identity = sdk.target_id, sdk._page, sdk.control.snapshot()
                call = page.call

                async def observed(method, params=None, timeout=20):
                    methods.append(method)
                    result = await call(method, params, timeout=timeout)
                    if method == "Page.captureScreenshot" and hold["enabled"]:
                        entered.set()
                        await release.wait()
                    return result  # Original real response; no data replacement.

                monkeypatch.setattr(page, "call", observed)
                with pytest.raises(ControlError, match="browser_authorization_denied"):
                    await sdk.diagnostics(
                        epoch,
                        target_epoch,
                        before_read=current,
                        authorize_frame=frame_grant,
                    )
                assert {f["origin"] for f in requests} == {origin, child_origin}
                assert not any(
                    m in {"DOM.getDocument", "Page.captureScreenshot"} for m in methods
                )
                permit["child"] = True
                result = await sdk.diagnostics(
                    epoch,
                    target_epoch,
                    before_read=current,
                    authorize_frame=frame_grant,
                )
                screenshot = result["screenshot"]
                raw = base64.b64decode(screenshot["data"], validate=True)
                with Image.open(io.BytesIO(raw)) as image:
                    assert image.height >= 2500 and image.height > 900
                    x = int(50 * image.width / screenshot["cssWidth"])
                    y = int(2450 * image.height / screenshot["cssHeight"])
                    assert image.convert("RGB").getpixel((x, y)) == (180, 20, 180)
                assert "diagnostic-original" in json.dumps(result["dom"])
                assert any(
                    node.get("name", {}).get("value") == "Original private diagnostic"
                    for node in result["accessibility"]
                )
                assert {f["origin"] for f in result["frames"]} == {origin, child_origin}
                assert (sdk.target_id, sdk._page, sdk.control.snapshot()) == identity
                (output / "actual-original-full-page.png").write_bytes(raw)
                hold["enabled"] = True
                pending = asyncio.create_task(
                    sdk.diagnostics(
                        epoch,
                        target_epoch,
                        before_read=current,
                        authorize_frame=frame_grant,
                    )
                )
                try:
                    async with asyncio.timeout(10):
                        await entered.wait()
                    permit["read"] = False
                    release.set()
                    with pytest.raises(
                        ControlError, match="browser_authorization_denied"
                    ):
                        await pending
                finally:
                    release.set()
                    if not pending.done():
                        await pending
                assert (
                    methods.count("Page.captureScreenshot") == 2
                    and not page._event_handlers
                )
                assert (sdk.target_id, sdk._page, sdk.control.snapshot()) == identity
                assert not any(m.startswith("Input.") for m in methods)
                (output / "observation.json").write_text(
                    json.dumps(
                        {
                            "sameOriginalSessionTargetPageAndControl": True,
                            "humanControlUnchanged": True,
                            "actualDomAndAccessibility": True,
                            "fullPageBelowViewportPixel": True,
                            "childSourcesRequireExplicitGrantBeforeDomPixels": True,
                            "actualScreenshotResponseThenReadWithdrawalNoResult": True,
                            "originalScreenshotCalls": 2,
                            "noInputReplayOrNativeReady": True,
                            "dimensions": {
                                "width": screenshot["width"],
                                "height": screenshot["height"],
                                "cssWidth": screenshot["cssWidth"],
                                "cssHeight": screenshot["cssHeight"],
                            },
                            "pngSha256": hashlib.sha256(raw).hexdigest(),
                            "methods": methods,
                            "fixtureGrantsNotActualMossworkProviderOrProduction": True,
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                await sdk.close()
                sdk = None
        finally:
            release.set()
            if sdk:
                await sdk.close()
            if client:
                await client.close()
            if launched and launched.get("session_id"):
                stopped = await asyncio.to_thread(
                    browser_stop, session_id=launched["session_id"]
                )
                assert stopped.get("stopped") is True
            await runner.cleanup()
            await child_runner.cleanup()
