"""Incremental writes use fixture capabilities; real process loss is tested live."""

import asyncio
import copy
import json

import pytest

from ai_dev_browser.record.capture import EventRecording
from ai_dev_browser.record.session import SessionRecording
from ai_dev_browser.remote.control import ControlError
from test_semantic_capture import Grants, Page, active, allowed


async def test_sink_receives_only_redacted_detached_native_events_in_order():
    rows = []

    async def sink(identity, event):
        assert identity == "original-recording"
        rows.append(copy.deepcopy(event))
        event["seq"] = -1
        event["page"]["origin"] = "changed by host"

    capture, page, _ = await active(event_sink=sink)
    try:
        page.event(
            "input",
            seq=999,
            targetId="forged",
            value="PASSWORD_FIXTURE_SECRET",
            target={"type": "password", "name": "password"},
            page={"url": "https://original.example/?token=URL_FIXTURE_SECRET"},
        )
        page.event("input", value="ordinary query", target={"name": "query"})
        await capture.drain()
        snapshot = await capture.snapshot(before_read=allowed)
        assert snapshot["events"] == rows
        assert [e["seq"] for e in rows] == [1, 2, 3]
        assert all(e["targetId"] == "original-target" for e in rows)
        assert all(e["page"]["origin"] == "https://original.example" for e in rows)
        assert "FIXTURE_SECRET" not in json.dumps(rows)
        assert rows[-1]["value"] == "ordinary query"
    finally:
        await capture.close()
        page.finish()


@pytest.mark.parametrize("outcome", ["lost", "false", "cancelled"])
async def test_possible_write_is_never_resent_or_released_as_partial_snapshot(outcome):
    writes = []

    async def sink(identity, event):
        writes.append((identity, copy.deepcopy(event)))
        if event["kind"] == "input":
            if outcome == "lost":
                raise ConnectionError("private error after the write")
            if outcome == "false":
                return False
            raise asyncio.CancelledError()

    capture, page, _ = await active(event_sink=sink)
    page.event("input", value="accepted once")
    page.event("input", value="never sent")
    with pytest.raises(
        ControlError, match="^browser_recording_event_write_unconfirmed$"
    ):
        await capture.drain()
    await capture.close()
    await capture.close()
    with pytest.raises(
        ControlError, match="^browser_recording_event_write_unconfirmed$"
    ):
        await capture.snapshot(before_read=allowed)
    assert [e[1]["seq"] for e in writes] == [1, 2]
    assert capture.status()["status"] == "failed" and not page.handlers
    page.finish()


async def test_frame_withdrawal_refuses_before_the_next_sink_call():
    writes = []

    async def sink(identity, event):
        writes.append(event)

    capture, page, grants = await active(event_sink=sink)
    grants.allowed = False
    page.event("input", value="must not reach writer")
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await capture.drain()
    await capture.close()
    assert len(writes) == 1 and writes[0]["kind"] == "recorder_installed"
    page.finish()


async def session_with_sink(event_sink, *, before_read=allowed, before_capture=allowed):
    terminal = []

    async def persist(payload):
        terminal.append(payload)

    page = Page()
    record = SessionRecording(
        "original-recording",
        "original-human",
        before_capture=before_capture,
        authorize_frame=Grants(),
        before_read=before_read,
        persist=persist,
        event_sink=event_sink,
    )
    await record.attach("original-target", page)
    return record, page, terminal


async def test_session_flushes_last_input_to_same_sink_before_one_terminal_publish():
    writes = []

    async def sink(identity, event):
        writes.append((identity, copy.deepcopy(event)))

    record, page, terminal = await session_with_sink(sink)
    assert len(writes) == 1 and terminal == []
    page.pending_input = "last debounced original input"
    result = await record.finish("original-human", before_read=allowed)
    assert result["storageStatus"] == "saved" and result["hasDraft"]
    assert terminal[0]["snapshot"]["events"] == [e for _, e in writes]
    assert writes[-1][1]["value"] == "last debounced original input"
    await record.finish("original-human", before_read=allowed)
    assert len(terminal) == 1 and len(writes) == 2
    page.finish()


@pytest.mark.parametrize("scope", ["read", "capture"])
async def test_session_current_authority_is_checked_before_each_event_write(scope):
    permitted = True
    writes = []

    async def current():
        if not permitted:
            raise PermissionError("fixture authority withdrawn")

    async def sink(identity, event):
        writes.append(event)

    record, page, terminal = await session_with_sink(
        sink,
        before_read=current if scope == "read" else allowed,
        before_capture=current if scope == "capture" else allowed,
    )
    permitted = False
    page.event("input", value="must not be checkpointed")
    with pytest.raises(
        ControlError, match="^browser_recording_event_write_unconfirmed$"
    ):
        await record.capture.drain()
    # Operational terminal metadata is still allowed, without private data.
    result = await record.finish("original-human", before_read=allowed)
    assert result["status"] == "failed" and not result["hasDraft"]
    assert len(writes) == 1 and terminal[0]["snapshot"] is None
    page.finish()


async def test_authority_withdrawn_while_sink_runs_withholds_successful_recording():
    permitted = True
    entered, release = asyncio.Event(), asyncio.Event()
    writes = []

    async def current():
        if not permitted:
            raise PermissionError("fixture recording read withdrawn")

    async def sink(identity, event):
        writes.append(event)
        if event["kind"] == "input":
            entered.set()
            await release.wait()

    record, page, terminal = await session_with_sink(sink, before_read=current)
    page.event("input", value="accepted before withdrawal")
    await entered.wait()
    permitted = False
    release.set()
    with pytest.raises(
        ControlError, match="^browser_recording_event_write_unconfirmed$"
    ):
        await record.capture.drain()
    await record.finish("original-human", before_read=allowed)
    assert len(writes) == 2
    assert terminal[0]["status"] == "failed"
    assert terminal[0]["snapshot"] is terminal[0]["draft"] is None
    page.finish()


async def test_cancelled_stop_drains_original_event_write_before_terminal_publish():
    entered, release = asyncio.Event(), asyncio.Event()
    writes = []

    async def sink(identity, event):
        writes.append(event)
        if event["kind"] == "input":
            entered.set()
            await release.wait()

    record, page, terminal = await session_with_sink(sink)
    page.pending_input = "stop flush"
    pending = asyncio.create_task(record.finish("original-human", before_read=allowed))
    await entered.wait()
    pending.cancel()
    await asyncio.sleep(0)
    assert not pending.done() and terminal == []
    assert record.status()["eventWritePending"] is True
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert record.phase == "saved" and len(terminal) == 1 and len(writes) == 2
    await record.finish("original-human", before_read=allowed)
    assert len(terminal) == 1 and len(writes) == 2
    page.finish()


async def test_original_twenty_second_bound_keeps_unknown_write_owned_without_publish():
    entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    writes = []

    async def sink(identity, event):
        writes.append(event)
        if event["kind"] == "input":
            entered.set()
            await release.wait()
            finished.set()

    record, page, terminal = await session_with_sink(sink)
    page.event("input", value="possibly committed original write")
    await entered.wait()
    closed = await record.capture.close()
    assert closed["status"] == "failed"
    assert closed["error"] == "browser_recording_event_write_unconfirmed"
    assert closed["eventWritePending"] is True
    with pytest.raises(ControlError, match="^browser_recording_write_unconfirmed$"):
        await record.finish("original-human", before_read=allowed)
    assert record.phase == "storage-unknown" and terminal == [] and len(writes) == 2
    with pytest.raises(ControlError, match="^browser_recording_write_unconfirmed$"):
        await record.confirm_saved(
            "original-human", before_read=allowed, reconcile=allowed
        )
    assert terminal == [] and not finished.is_set()
    release.set()
    await finished.wait()
    await asyncio.sleep(0)
    assert record.status()["eventWritePending"] is False
    with pytest.raises(ControlError, match="^browser_recording_write_unconfirmed$"):
        await record.finish("original-human", before_read=allowed)
    assert terminal == [] and len(writes) == 2
    page.finish()


@pytest.mark.parametrize("factory", [EventRecording, SessionRecording])
def test_invalid_optional_sink_refuses_before_capture(factory):
    kwargs = {"event_sink": False}
    args = ["original"]
    if factory is SessionRecording:
        args.append("original-human")
        kwargs.update(
            before_capture=allowed,
            authorize_frame=Grants(),
            before_read=allowed,
            persist=allowed,
        )
    with pytest.raises(ControlError, match="^browser_recording_store_required$"):
        factory(*args, **kwargs)
