"""Actual SDK Chrome capture; grants and website are explicit fixtures.

This is not a Mosswork factory/current-principal/model/production acceptance.
The native lifecycle registry stays in a private temporary folder, outside
public CI observations. The original SDK ownership/start/stop checks remain.
"""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

import aiohttp
from aiohttp import web
import pytest

from ai_dev_browser.core import _session
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser
from ai_dev_browser.record.capture import EventRecording
from ai_dev_browser.record.draft import build_recording_draft
from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.session import BrowserSession


async def serve(app):
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"


async def current_fixture():
    return None


async def test_original_sdk_browser_records_frames_and_retires_only_capture(
    tmp_path, monkeypatch
):
    child = web.Application()
    child.router.add_get(
        "/frame",
        lambda request: web.Response(
            text='<!doctype html><meta charset="utf-8"><style>body{margin:8px}input{height:32px;width:200px}</style>'
            '<label>Frame query<input id="child" name="frame_query"></label>',
            content_type="text/html",
        ),
    )
    child_runner, child_origin = await serve(child)
    app = web.Application()

    async def page_fixture(request):
        return web.Response(
            text=f"""<!doctype html><meta charset="utf-8">
        <style>body{{margin:16px}}label{{display:block;margin:8px 0}}input[type=text],input[type=password]{{width:220px;height:30px}}iframe{{display:block;height:90px;width:360px;margin:8px 0}}</style>
        <label>Query<input id="query" name="query" type="text"></label>
        <label>Password<input id="password" type="password" value="INITIAL_CAPTURE_SECRET"></label>
        <label><input id="check" type="checkbox" checked>Enabled</label>
        <iframe id="frame" src="{child_origin}/frame"></iframe>
        <label>Tail<input id="tail" name="tail" type="text"></label>
        """,
            content_type="text/html",
        )

    app.router.add_get("/", page_fixture)
    runner, origin = await serve(app)
    parent = os.environ.get("AI_DEV_BROWSER_CAPTURE_PRIVATE_ROOT")
    if parent:
        Path(parent).mkdir(parents=True, exist_ok=True)
    client = None
    capture = None
    session = None
    launched = None
    checks = []
    with tempfile.TemporaryDirectory(
        prefix="adb-semantic-private-", dir=parent
    ) as private:
        monkeypatch.setattr(_session, "_DIR", Path(private) / "sessions")
        try:
            launched = await asyncio.to_thread(
                browser_start,
                headless=True,
                temp=True,
                stealth=False,
                transport="cdp",
                url=origin + "/",
                chrome_path=os.environ.get("AI_DEV_BROWSER_CHROME"),
                silent_stderr=True,
                extra_args=["--no-sandbox"] if sys.platform == "linux" else [],
            )
            assert "error" not in launched, {
                "error_code": launched.get("error_code"),
                "started": launched.get("started"),
            }
            client = await connect_browser(session_id=launched["session_id"])
            async with aiohttp.ClientSession() as http:
                session = BrowserSession(client, http)
                initial = await session.state(before_effect=current_fixture)
                target = initial["activeTargetId"]
                page = await session._connect_page()
                original_owner = page.on_event
                scopes = []
                denied = set()
                next_root = asyncio.Event()

                async def frame_assertion(
                    actual_target, frame, context, unique_context, source_origin
                ):
                    assert actual_target == target
                    assert isinstance(unique_context, str) and unique_context
                    assert source_origin in {origin, child_origin}
                    prior_roots = [
                        scope for scope in scopes if scope["origin"] == origin
                    ]
                    scopes.append(
                        {
                            "frame": frame,
                            "origin": source_origin,
                            "contextUniqueId": unique_context,
                        }
                    )
                    if source_origin == origin and prior_roots:
                        next_root.set()

                    async def check():
                        if source_origin in denied:
                            raise PermissionError(
                                "explicit fixture frame grant revoked"
                            )

                    return check

                capture = EventRecording("original-capture", show_indicator=False)
                result = await capture.attach_source(
                    target,
                    page,
                    before_effect=current_fixture,
                    authorize_frame=frame_assertion,
                )
                assert result["status"] == "recording"
                await capture.drain()
                assert {scope["origin"] for scope in scopes} == {origin, child_origin}
                assert (
                    await page.js("typeof globalThis.__adbSemanticRecorder")
                    == "undefined"
                )
                assert page.on_event is original_owner
                checks.append(
                    "actual isolated frames admitted independently on original SDK target"
                )
                held = await session.take(
                    "user-capture-fixture",
                    initial["controlEpoch"],
                    initial["targetEpoch"],
                    before_effect=current_fixture,
                )
                epoch, target_epoch = held["controlEpoch"], held["targetEpoch"]

                async def click(selector):
                    point = await page.js(
                        f"(()=>{{const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}}}})()"
                    )
                    await session.action(
                        "user-capture-fixture",
                        epoch,
                        target_epoch,
                        {
                            "kind": "input",
                            "input": {"kind": "click", **point},
                        },
                        before_effect=current_fixture,
                    )

                async def text(value):
                    await session.action(
                        "user-capture-fixture",
                        epoch,
                        target_epoch,
                        {
                            "kind": "input",
                            "input": {"kind": "text", "text": value},
                        },
                        before_effect=current_fixture,
                    )

                await click("#query")
                await text("原始实际查询")
                await click("#password")
                await text("TYPED_CAPTURE_SECRET")
                await click("#check")
                assert (
                    await page.js("document.querySelector('#check').checked") is False
                )
                rectangle = await page.js(
                    "(()=>{const r=document.querySelector('#frame').getBoundingClientRect();return {x:r.x,y:r.y}})()"
                )
                await session.action(
                    "user-capture-fixture",
                    epoch,
                    target_epoch,
                    {
                        "kind": "input",
                        "input": {
                            "kind": "click",
                            "x": rectangle["x"] + 100,
                            "y": rectangle["y"] + 25,
                        },
                    },
                    before_effect=current_fixture,
                )
                await text("frame actual input")
                await click("#tail")
                await text("last pending input")
                stopped = await capture.close()
                assert (
                    stopped["status"] == "stopped" and not stopped["cleanupUncertain"]
                )
                snapshot = await capture.snapshot(before_read=current_fixture)
                serialized = json.dumps(snapshot, ensure_ascii=False)
                assert (
                    "原始实际查询" in serialized and "last pending input" in serialized
                )
                assert "frame actual input" in serialized
                assert (
                    "INITIAL_CAPTURE_SECRET" not in serialized
                    and "TYPED_CAPTURE_SECRET" not in serialized
                )
                assert any(
                    event.get("checked") is False for event in snapshot["events"]
                )
                assert all(event["targetId"] == target for event in snapshot["events"])
                assert any(
                    event.get("target", {}).get("framePath") == [child_origin]
                    for event in snapshot["events"]
                    if event.get("value") == "frame actual input"
                )
                draft = build_recording_draft("original-capture", snapshot["events"])
                assert any(
                    step["kind"] == "set_checked" and step["value"] == "false"
                    for step in draft["steps"]["steps"]
                )
                assert any(
                    item["kind"] == "secret" and "example" not in item
                    for item in draft["steps"]["inputs"]
                )
                checks.extend(
                    [
                        "actual trusted SDK input captured in root and cross-origin iframe",
                        "password values absent and unchecked state retained",
                        "stop preserves final input and produces original semantic schema",
                    ]
                )
                count = capture.status()["events"]
                assert not page._event_handlers and not page.reader.done()
                assert (
                    session.control.state == "human"
                    and session.control.controller == "user-capture-fixture"
                )
                await click("#tail")
                await text(" after stop")
                assert capture.status()["events"] == count
                assert " after stop" in await page.js(
                    "document.querySelector('#tail').value"
                )
                checks.append(
                    "capture retirement preserves same browser, page and human lease"
                )

                navigation_capture = EventRecording(
                    "navigation-capture", show_indicator=False
                )
                try:
                    await navigation_capture.attach_source(
                        target,
                        page,
                        before_effect=current_fixture,
                        authorize_frame=frame_assertion,
                    )
                    original_contexts = navigation_capture.source_scopes()
                    next_root.clear()
                    await page.call(
                        "Page.navigate", {"url": origin + "/?document=next"}
                    )
                    await asyncio.wait_for(next_root.wait(), 20)
                    await navigation_capture.drain()
                    current_contexts = navigation_capture.source_scopes()
                    root_scopes = [
                        scope for scope in current_contexts if scope["origin"] == origin
                    ]
                    assert len(root_scopes) == 2
                    assert (
                        root_scopes[0]["contextUniqueId"]
                        != root_scopes[1]["contextUniqueId"]
                    )
                    assert current_contexts != original_contexts
                    await click("#query")
                    await text("new native document input")
                    assert (await navigation_capture.close())["status"] == "stopped"
                    new_document = await navigation_capture.snapshot(
                        before_read=current_fixture
                    )
                    assert any(
                        event.get("value") == "new native document input"
                        for event in new_document["events"]
                    )
                    assert not page._event_handlers and not page.reader.done()
                finally:
                    await navigation_capture.close()
                checks.append(
                    "actual navigation admits new native document before collecting input"
                )

                async def denied_read():
                    raise PermissionError("fixture current read grant withdrawn")

                with pytest.raises(
                    ControlError, match="^browser_authorization_denied$"
                ):
                    await capture.snapshot(before_read=denied_read)
                checks.append("current snapshot-read withdrawal withholds stored data")

                denied.add(child_origin)
                refused = EventRecording("refused-frame-capture", show_indicator=False)
                try:
                    with pytest.raises(
                        ControlError, match="^browser_authorization_denied$"
                    ):
                        await refused.attach_source(
                            target,
                            page,
                            before_effect=current_fixture,
                            authorize_frame=frame_assertion,
                        )
                    assert (await refused.close())["status"] == "failed"
                    assert not page._event_handlers and not page.reader.done()
                    assert page.on_event is original_owner
                finally:
                    await refused.close()
                checks.append(
                    "actual new iframe admission refuses without a page-reader fallback"
                )
                safe = {
                    "checks": checks,
                    "fixtureGrants": True,
                    "fixtureWebsite": True,
                    "sameSdkOriginalSession": True,
                    "eventCount": len(snapshot["events"]),
                    "rawSnapshotSha256": hashlib.sha256(
                        serialized.encode()
                    ).hexdigest(),
                    "eventKinds": sorted(
                        {event["kind"] for event in snapshot["events"]}
                    ),
                    "productionProviderOrMossworkFactory": False,
                    "oopifPersonalExtensionPhoneOrProductionAcceptance": False,
                }
                (tmp_path / "semantic-capture-observation.json").write_text(
                    json.dumps(safe, indent=2) + "\n", encoding="utf-8"
                )
                await session.close()
                session = None
        finally:
            if capture:
                await capture.close()
            if session:
                await session.close()
            if client:
                await client.close()
            if launched and launched.get("session_id"):
                stopped_browser = await asyncio.to_thread(
                    browser_stop, session_id=launched["session_id"]
                )
                assert stopped_browser.get("stopped") is True
            await runner.cleanup()
            await child_runner.cleanup()
