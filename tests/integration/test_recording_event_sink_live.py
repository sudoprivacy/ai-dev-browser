"""Real Chrome, native input and host journal; fixture grants, no Product rollout."""

import asyncio
import hashlib
import json
import os
import sys

import aiohttp
from aiohttp import web
import pytest

from ai_dev_browser.core.connection import BrowserClient, get_active_tab
from ai_dev_browser.core.navigation import page_goto
from tests.integration.semantic_event_sink_support import (
    Journal,
    QUERY,
    SECRET,
    click,
    current_fixture,
    inspect_journal,
    start_recording,
    submit_original_form,
    type_text,
)
from tests.integration.test_remote_view import wait_for
from tests.integration.test_semantic_capture_live import serve
from tests.integration.test_session_operations_live import (
    owned_operations_browser,
)

incremental_browser = owned_operations_browser


@pytest.fixture
async def incremental_site():
    receipts = []

    async def form(request):
        return web.Response(
            text="""<!doctype html><meta charset=utf-8>
<title>Retained semantic recording</title><style>body{margin:24px;font:20px sans-serif}
input,button{display:block;width:300px;height:42px;margin:16px 0}</style>
<label>Query<input id=query name=query></label><label>Password<input id=password type=password></label>
<form id=form><button id=submit>Submit once</button></form><label>Tail<input id=tail name=tail></label>
<p id=result>Waiting</p><script>form.onsubmit=async e=>{e.preventDefault();
await fetch('/receipt',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({query:query.value,password:password.value,trusted:e.isTrusted})});
result.textContent='Saved';};</script>""",
            content_type="text/html",
        )

    async def receipt(request):
        data = await request.json()
        data["passwordSha256"] = hashlib.sha256(
            data.pop("password").encode()
        ).hexdigest()
        receipts.append(data)
        return web.json_response({"saved": True})

    app = web.Application()
    app.router.add_get("/", form)
    app.router.add_post("/receipt", receipt)
    runner, origin = await serve(app)
    try:
        yield origin, receipts
    finally:
        await runner.cleanup()


async def incremental_journey(browser, tmp_path, incremental_site, lose_ack):
    origin, receipts = incremental_site
    await page_goto(await get_active_tab(browser), origin)
    session = None
    journal = Journal(tmp_path / "original-events.jsonl", lose_input_ack=lose_ack)
    terminal = []
    try:
        async with aiohttp.ClientSession() as http:
            session, page = await start_recording(
                browser, http, origin, journal, terminal
            )
            original_target, original_reader = session.target_id, page.reader
            if lose_ack:
                await click(session, page, "#query")
                await type_text(session, QUERY)
                await click(session, page, "#password")

                async def status():
                    return await session.recording_status(
                        "original-human",
                        session.control.epoch,
                        session.control.target_epoch,
                        before_effect=current_fixture,
                    )

                await wait_for(status, lambda value: value["status"] == "failed")
                assert (
                    len(
                        [
                            row
                            for row in journal.rows()
                            if row["event"]["kind"] in {"input", "change"}
                        ]
                    )
                    == 1
                )
            else:
                await submit_original_form(session, page)

                async def submitted():
                    return receipts

                await wait_for(submitted, lambda value: len(value) == 1)
                assert receipts == [
                    {
                        "query": QUERY,
                        "passwordSha256": hashlib.sha256(SECRET.encode()).hexdigest(),
                        "trusted": True,
                    }
                ]
                inspect_journal(journal.path)
                assert terminal == []  # Actual bytes exist before terminal save.
                await click(session, page, "#tail")
                await type_text(session, "last pending original input")
            result = await session.stop_recording(
                "original-human",
                session.control.epoch,
                session.control.target_epoch,
                before_effect=current_fixture,
                before_read=current_fixture,
                skill_name="Incremental original workflow",
            )
            assert result["storageStatus"] == "saved" and len(terminal) == 1
            rows = journal.rows()
            assert [row["event"]["seq"] for row in rows] == list(
                range(1, len(rows) + 1)
            )
            if lose_ack:
                assert result["status"] == "failed" and not result["hasDraft"]
                assert terminal[0]["snapshot"] is terminal[0]["draft"] is None
                assert (
                    terminal[0]["error"] == "browser_recording_event_write_unconfirmed"
                )
            else:
                assert result["status"] == "stopped" and result["hasDraft"]
                assert terminal[0]["snapshot"]["events"] == [
                    row["event"] for row in rows
                ]
                assert any(
                    row["event"].get("value") == "last pending original input"
                    for row in rows
                )
                assert (
                    terminal[0]["draft"]["steps"]["recordingId"]
                    == "retained-original-recording"
                )
            count = len(journal.calls)
            await session.stop_recording(
                "original-human",
                session.control.epoch,
                session.control.target_epoch,
                before_effect=current_fixture,
                before_read=current_fixture,
            )
            assert len(journal.calls) == count and len(terminal) == 1
            assert session.target_id == original_target and not original_reader.done()
            await page.js("document.title")
            (tmp_path / "incremental-recording-evidence.json").write_text(
                json.dumps(
                    {
                        "publicApi": "BrowserSession.start_recording(event_sink=...)",
                        "originalId": result["recordingId"],
                        "transport": browser.transport,
                        "lostSinkAck": lose_ack,
                        "events": len(rows),
                        "terminalWrites": len(terminal),
                        "status": result["status"],
                        "hasDraft": result["hasDraft"],
                        "originalTargetAndReaderPreserved": True,
                        "productionAuthority": False,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            await session.close()
            session = None
    finally:
        if session:
            await session.close()


@pytest.mark.parametrize("lose_ack", [False, True], ids=["confirmed", "lost-ack"])
async def test_original_session_checkpoints_redacted_events_before_terminal(
    incremental_browser,
    tmp_path,
    incremental_site,
    lose_ack,
):
    await incremental_journey(incremental_browser, tmp_path, incremental_site, lose_ack)


@pytest.mark.parametrize("lose_ack", [False, True], ids=["confirmed", "lost-ack"])
async def test_extension_session_checkpoints_redacted_events_before_terminal(
    live_extension,
    tmp_path,
    incremental_site,
    lose_ack,
):
    browser = await BrowserClient.connect(
        "127.0.0.1",
        live_extension.port,
        ws_url=f"ws://127.0.0.1:{live_extension.port}/devtools/browser",
    )
    browser.transport = "extension"
    browser._automation_target_id = str(
        live_extension.bridge.identity["automation_target_id"]
    )
    try:
        await incremental_journey(browser, tmp_path, incremental_site, lose_ack)
    finally:
        await browser.close()


async def test_acknowledged_events_survive_real_recorder_process_loss_before_stop(
    incremental_browser,
    tmp_path,
    incremental_site,
):
    browser = incremental_browser
    origin, receipts = incremental_site
    await page_goto(await get_active_tab(browser), origin)
    journal = tmp_path / "retained-events.jsonl"
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    stderr_path = tmp_path / "recorder-process.stderr.log"
    child = None
    with stderr_path.open("wb") as stderr:
        try:
            child = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "tests.integration.semantic_event_sink_process",
                "--port",
                str(browser.port),
                "--origin",
                origin,
                "--journal",
                str(journal),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr,
                env=env,
            )
            line = await asyncio.wait_for(child.stdout.readline(), 30)
            assert line, stderr_path.read_text(encoding="utf-8")
            captured = json.loads(line)
            assert captured["capturedBeforeStop"] is True
            assert (
                len(receipts) == 1
                and receipts[0]["query"] == QUERY
                and receipts[0]["trusted"]
            )
            before = journal.read_bytes()
            child.kill()  # Exactly this owned recorder; its parent owns Chrome.
            await asyncio.wait_for(child.wait(), 10)
            assert child.returncode != 0
            reader = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "tests.integration.semantic_event_sink_process",
                "--read-journal",
                "--journal",
                str(journal),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr_bytes = await asyncio.wait_for(reader.communicate(), 15)
            assert reader.returncode == 0, stderr_bytes.decode()
            recovered = json.loads(stdout)
            assert recovered["sha256"] == captured["sha256"]
            assert recovered["recordingId"] == "retained-original-recording"
            assert journal.read_bytes() == before
            (tmp_path / "process-loss-recovery-evidence.json").write_text(
                json.dumps(
                    {
                        "recordingId": recovered["recordingId"],
                        "events": recovered["events"],
                        "recoveredSha256": recovered["sha256"],
                        "freshReaderProcess": True,
                        "endedBeforeStop": True,
                        "terminalPublication": False,
                        "realBrowserSubmissions": len(receipts),
                        "powerLossGuarantee": False,
                        "productionAuthority": False,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        finally:
            if child is not None and child.returncode is None:
                child.kill()
                await child.wait()
