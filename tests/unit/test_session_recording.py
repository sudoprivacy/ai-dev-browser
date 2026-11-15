"""Actual capture coordinator; page transport/grants and sink are fixtures."""

import asyncio
import copy
import hashlib
import json

import pytest

from ai_dev_browser.record.session import SessionRecording
from ai_dev_browser.remote.control import ControlError
from test_semantic_capture import Page, Grants, allowed


async def active(persist=None, read=allowed):
    written = []

    async def sink(payload):
        written.append(copy.deepcopy(payload))

    page, grants = Page(), Grants()
    record = SessionRecording(
        "original-recording",
        "original-human",
        before_capture=allowed,
        authorize_frame=grants,
        before_read=read,
        persist=persist or sink,
    )
    await record.attach("original-target", page)
    return record, page, grants, written


@pytest.mark.parametrize(
    "missing", ["before_capture", "authorize_frame", "before_read", "persist"]
)
def test_missing_record_capability_refuses_before_page_or_storage(missing):
    arguments = dict(
        before_capture=allowed,
        authorize_frame=Grants(),
        before_read=allowed,
        persist=allowed,
    )
    arguments[missing] = None
    with pytest.raises(
        ControlError,
        match="^(browser_authorization_required|browser_recording_store_required)$",
    ):
        SessionRecording("original", "original-human", **arguments)


async def test_stop_preserves_last_input_and_withholds_saved_until_actual_sink_ack():
    entered, release = asyncio.Event(), asyncio.Event()
    payloads = []

    async def sink(payload):
        payloads.append(copy.deepcopy(payload))
        entered.set()
        await release.wait()

    record, page, _, _ = await active(sink)
    page.pending_input = "last original value"
    pending = asyncio.create_task(record.finish("original-human", before_read=allowed))
    await entered.wait()
    assert not pending.done() and record.status()["storageStatus"] == "pending-save"
    assert payloads[0]["snapshot"]["events"][-1]["value"] == "last original value"
    assert payloads[0]["draft"]["steps"]["recordingId"] == "original-recording"
    release.set()
    assert (await pending)["storageStatus"] == "saved"
    assert (await record.finish("original-human", before_read=allowed))[
        "storageStatus"
    ] == "saved"
    assert len(payloads) == 1 and not page.reader.done() and not page.handlers
    page.finish()


async def test_other_owner_cannot_stop_or_save_original_capture():
    record, page, _, written = await active()
    with pytest.raises(ControlError, match="^browser_recording_not_owned$"):
        await record.finish("other-human", before_read=allowed)
    assert written == [] and record.phase == "recording" and page.handlers
    await record.finish("original-human", before_read=allowed)
    page.finish()


async def test_committed_then_failed_sink_reconciles_read_only_without_second_write():
    writes = []

    async def sink(payload):
        writes.append(copy.deepcopy(payload))
        raise ConnectionError("private write reply lost after commit")

    record, page, _, _ = await active(sink)
    with pytest.raises(ControlError, match="^browser_recording_write_unconfirmed$"):
        await record.finish("original-human", before_read=allowed)
    assert record.phase == "storage-unknown" and len(writes) == 1
    with pytest.raises(ControlError, match="^browser_recording_write_unconfirmed$"):
        await record.finish("original-human", before_read=allowed)
    assert len(writes) == 1
    queries = []

    async def reconcile(payload, digest):
        queries.append(digest)
        assert writes == [payload]
        assert (
            hashlib.sha256(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest()
            == digest
        )

    status = await record.finish(
        "original-human", before_read=allowed, reconcile=reconcile
    )
    assert status["storageStatus"] == "saved" and len(writes) == len(queries) == 1
    assert status["recordingId"] == "original-recording"
    page.finish()


async def test_cancelled_stop_drains_original_persistence_and_never_repeats_it():
    entered, release = asyncio.Event(), asyncio.Event()
    writes = []

    async def sink(payload):
        entered.set()
        await release.wait()
        writes.append(payload)

    record, page, _, _ = await active(sink)
    pending = asyncio.create_task(record.finish("original-human", before_read=allowed))
    await entered.wait()
    pending.cancel()
    await asyncio.sleep(0)
    assert not pending.done() and record.phase == "pending-save"
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert record.phase == "saved" and len(writes) == 1
    await record.finish("original-human", before_read=allowed)
    assert len(writes) == 1
    page.finish()


async def test_stopped_record_never_reopens_capture_when_source_changes():
    record, first, _, written = await active()
    first.pending_input = "first tab value"
    await record.detach()
    second = Page()
    await record.attach("second-target", second)
    second.pending_input = "second tab value"
    await record.finish("original-human", before_read=allowed)
    events = written[0]["snapshot"]["events"]
    assert any(
        e.get("value") == "first tab value" and e["targetId"] == "original-target"
        for e in events
    )
    assert any(
        e.get("value") == "second tab value" and e["targetId"] == "second-target"
        for e in events
    )
    await record.attach("third", Page())
    assert record.current is None and not first.handlers and not second.handlers
    first.finish()
    second.finish()


async def test_cleanup_after_read_revocation_saves_only_failed_terminal_metadata():
    calls = []

    async def denied_read():
        calls.append("read")
        raise PermissionError("original human read withdrawn")

    record, page, grants, written = await active(read=denied_read)
    page.pending_input = "private unflushed value"
    grants.allowed = False
    await record.interrupt()
    assert calls == [] and len(written) == 1
    assert (
        written[0]["status"] == "failed"
        and written[0]["error"] == "browser_recording_interrupted"
    )
    assert written[0]["snapshot"] is None and written[0]["draft"] is None
    assert "private unflushed value" not in json.dumps(written)
    assert not page.handlers and not page.reader.done()
    page.finish()


async def test_non_none_sink_result_cannot_claim_durable_save():
    async def wrong(payload):
        return True

    record, page, _, _ = await active(wrong)
    with pytest.raises(ControlError, match="^browser_recording_write_unconfirmed$"):
        await record.finish("original-human", before_read=allowed)
    assert record.phase == "storage-unknown"
    page.finish()


async def test_sdk_input_waits_for_actual_new_document_admission():
    record, page, grants, _ = await active()
    entered, release = asyncio.Event(), asyncio.Event()

    async def resolve(target, frame, context, unique_id, origin):
        assertion = await grants(target, frame, context, unique_id, origin)
        if unique_id == "new-original-document":
            entered.set()
            await release.wait()
        return assertion

    source = record.capture._sources["original-target"]
    source.authorize = resolve
    page.emit("Runtime.executionContextDestroyed", {"executionContextId": 1})
    page.context(2, "root", "https://new.example", unique_id="new-original-document")
    await entered.wait()
    gate = asyncio.create_task(record.prepare_input("original-target", page))
    await asyncio.sleep(0)
    assert not gate.done() and not source.frames.get("new-original-document")
    release.set()
    await gate
    assert source.frames["new-original-document"].last_sequence == 1
    await record.finish("original-human", before_read=allowed)
    page.finish()


async def test_revoked_original_frame_grant_refuses_sdk_input_before_any_event():
    record, page, grants, written = await active()
    grants.allowed = False
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await record.prepare_input("original-target", page)
    await record.interrupt()
    assert written[0]["status"] == "failed" and written[0]["snapshot"] is None
    assert not page.handlers
    page.finish()
