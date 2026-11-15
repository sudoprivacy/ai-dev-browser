"""Real extension event capture keeps the existing page, input and owner."""

import base64
import json

import aiohttp
from aiohttp import web

from ai_dev_browser.core import page_goto
from ai_dev_browser.core.connection import BrowserClient
from ai_dev_browser.record.capture import EventRecording
from ai_dev_browser.record.draft import build_recording_draft
from ai_dev_browser.remote.session import BrowserSession
from tests.integration.test_remote_view import wait_for
from tests.integration.test_semantic_capture_live import current_fixture, serve


async def test_extension_captures_navigation_and_private_input_without_reconnecting(
    live_extension, tmp_path
):
    receipts = []

    async def website(_request):
        return web.Response(
            text="""<!doctype html><meta charset=utf-8><title>Record a request</title>
<style>body{margin:24px;font:20px sans-serif}input,button{display:block;margin:20px;height:44px;width:300px}</style>
<h1>Record a request</h1><label>Request name<input id=query name=query></label>
<label>Password<input id=password type=password></label><button id=save>Save once</button><p id=result>Draft</p>
<script>document.querySelector('#save').onclick=async e=>{
await fetch('/receipt',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({query:document.querySelector('#query').value,trusted:e.isTrusted})});
document.querySelector('#result').textContent='Saved';};</script>""",
            content_type="text/html",
        )

    async def receive(request):
        receipts.append(await request.json())
        return web.json_response({"saved": True})

    app = web.Application()
    app.router.add_get("/", website)
    app.router.add_get("/next", website)
    app.router.add_post("/receipt", receive)
    runner, origin = await serve(app)
    client, session, capture = None, None, None
    try:
        await live_extension.call(
            page_goto,
            url=origin
            + "/?token=QUERY_FIXTURE_SECRET#access_token=FRAGMENT_FIXTURE_SECRET",
        )
        client = await BrowserClient.connect(
            "127.0.0.1",
            live_extension.port,
            ws_url=f"ws://127.0.0.1:{live_extension.port}/devtools/browser",
        )
        client.transport = "extension"
        target = str(live_extension.bridge.identity["automation_target_id"])
        client._automation_target_id = target
        async with aiohttp.ClientSession() as http:
            session = BrowserSession(client, http)
            initial = await session.state(before_effect=current_fixture)
            assert initial["activeTargetId"] == target
            page = await session._connect_page()
            original_owner, original_reader = page.on_event, page.reader
            scopes = []

            async def authorize_frame(
                actual_target, frame, context, unique_id, source_origin
            ):
                assert actual_target == target and source_origin == origin
                assert unique_id and frame and type(context) is int
                scopes.append(unique_id)
                return current_fixture

            capture = EventRecording("extension-request")
            await capture.attach_source(
                target,
                page,
                before_effect=current_fixture,
                authorize_frame=authorize_frame,
            )
            held = await session.take(
                "user-recording",
                initial["controlEpoch"],
                initial["targetEpoch"],
                before_effect=current_fixture,
            )
            epoch, target_epoch = held["controlEpoch"], held["targetEpoch"]

            async def action(kind, **params):
                return await session.action(
                    "user-recording",
                    epoch,
                    target_epoch,
                    {"kind": kind, **params},
                    before_effect=current_fixture,
                )

            async def click(selector):
                point = await page.js(
                    f"(()=>{{let r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}}}})()"
                )
                await action("input", input={"kind": "click", **point})

            await click("#query")
            await action(
                "input", input={"kind": "text", "text": "first recorded request"}
            )
            await click("#password")
            await action(
                "input", input={"kind": "text", "text": "PASSWORD_FIXTURE_SECRET"}
            )
            await click("#save")
            await wait_for(
                lambda: page.js("document.querySelector('#result').textContent"),
                lambda value: value == "Saved",
            )
            assert receipts == [{"query": "first recorded request", "trusted": True}]
            # A genuine document navigation must get a new native unique ID.
            await action("navigate", url=origin + "/next")
            await wait_for(
                lambda: page.js(
                    "document.querySelector('[id^=__adb_recording_]') !== null"
                ),
                lambda value: value is True,
            )
            await click("#query")
            await action(
                "input", input={"kind": "text", "text": "final pending request"}
            )
            png = await page.call("Page.captureScreenshot", {"format": "png"})
            (tmp_path / "semantic-extension-accepted.png").write_bytes(
                base64.b64decode(png["data"])
            )
            stopped = await capture.close()
            assert stopped["status"] == "stopped" and not stopped["cleanupUncertain"]
            snapshot = await capture.snapshot(before_read=current_fixture)
            serialized = json.dumps(snapshot)
            for secret in (
                "QUERY_FIXTURE_SECRET",
                "FRAGMENT_FIXTURE_SECRET",
                "PASSWORD_FIXTURE_SECRET",
            ):
                assert secret not in serialized
            assert (
                "first recorded request" in serialized
                and "final pending request" in serialized
            )
            assert len(set(scopes)) >= 2
            draft = build_recording_draft("extension-request", snapshot["events"])
            assert draft["steps"]["steps"] and draft["skillDraft"]
            assert any(item["kind"] == "secret" for item in draft["steps"]["inputs"])
            assert page.reader is original_reader and page.on_event is original_owner
            assert not page._event_handlers and not page.disconnected
            assert session.control.state == "human" and session.target_id == target
            assert not await page.js(
                "document.querySelector('[id^=__adb_recording_]') !== null"
            )
            await action("input", input={"kind": "text", "text": " after stop"})
            assert (
                await page.js("document.querySelector('#query').value")
                == "final pending request after stop"
            )
            (tmp_path / "semantic-extension-evidence.json").write_text(
                json.dumps(
                    {
                        "events": len(snapshot["events"]),
                        "documents": len(set(scopes)),
                        "receipts": receipts,
                        "samePageConnection": page.reader is original_reader,
                        "stopped": stopped,
                        "humanLeasePreserved": session.control.state == "human",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
    finally:
        if capture:
            await capture.close()
        if session:
            await session.close()
        if client:
            await client.close()
        await runner.cleanup()
