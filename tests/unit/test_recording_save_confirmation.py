"""Public read-only recovery; page, authorization and durable store are fixtures."""

import asyncio
from types import SimpleNamespace

import pytest

from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.session import BrowserSession
from test_semantic_capture import allowed
from test_session_recording import active


async def unknown():
    writes = []

    async def persist(payload):
        writes.append(payload)
        raise ConnectionError("fixture saved then lost its reply")

    record, page, _, _ = await active(persist)
    with pytest.raises(ControlError, match="^browser_recording_write_unconfirmed$"):
        await record.finish("original-human", before_read=allowed)
    session = BrowserSession(
        SimpleNamespace(_automation_target_id="original-target"), None
    )
    session._recording = record
    return session, record, page, writes


async def test_public_confirmation_under_held_barrier_uses_original_payload_once():
    session, record, page, writes = await unknown()
    reads = []

    async def reader(payload, digest):
        assert payload == writes[0] and len(digest) == 64
        reads.append(digest)
        payload.clear()  # The callback owns a detached copy.

    try:
        async with session.control._operations:
            result = await asyncio.wait_for(
                session.confirm_recording_save(
                    "original-human",
                    "original-recording",
                    before_read=allowed,
                    reconcile=reader,
                ),
                1,
            )
            assert result["storageStatus"] == "saved"
            assert result["recordingId"] == "original-recording"
            await session.close()
        await session.confirm_recording_save(
            "original-human",
            "original-recording",
            before_read=allowed,
            reconcile=reader,
        )
        assert len(writes) == len(reads) == 1 and record is session._recording
    finally:
        page.finish()


@pytest.mark.parametrize(
    "case",
    ["owner", "identity", "missing-reader", "denied", "no-resolver", "malformed"],
)
async def test_public_confirmation_refuses_without_original_current_reader(case):
    session, record, page, writes = await unknown()
    reads = []

    async def reader(payload, digest):
        reads.append(digest)
        return False if case == "malformed" else None

    async def current():
        if case == "denied":
            raise PermissionError("fixture reader withdrawn")

    try:
        with pytest.raises(ControlError):
            await session.confirm_recording_save(
                "other" if case == "owner" else "original-human",
                "other" if case == "identity" else "original-recording",
                before_read=None if case == "missing-reader" else current,
                reconcile=None if case == "no-resolver" else reader,
            )
        assert len(reads) == (1 if case == "malformed" else 0)
        assert record.phase == "storage-unknown" and len(writes) == 1
        with pytest.raises(ControlError, match="^browser_recording_write_unconfirmed$"):
            await session.close()
        assert session._recording is record and not page.reader.done()
    finally:
        page.finish()


@pytest.mark.parametrize("change", ["withdraw", "replace"])
async def test_reader_or_recording_change_during_confirmation_preserves_unknown(change):
    session, record, page, writes = await unknown()
    grant = True

    async def current():
        if not grant:
            raise PermissionError("fixture current reader withdrawn")

    async def reader(payload, digest):
        nonlocal grant
        if change == "withdraw":
            grant = False
        else:
            session._recording = object()

    try:
        with pytest.raises(ControlError, match="^browser_recording_write_unconfirmed$"):
            await session.confirm_recording_save(
                "original-human",
                "original-recording",
                before_read=current,
                reconcile=reader,
            )
        assert record.phase == "storage-unknown" and len(writes) == 1
    finally:
        page.finish()


async def test_cancelled_confirmation_keeps_original_unknown_save_and_releases_read_lock():
    session, record, page, writes = await unknown()
    entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def reader(payload, digest):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    pending = asyncio.create_task(
        session.confirm_recording_save(
            "original-human",
            "original-recording",
            before_read=allowed,
            reconcile=reader,
        )
    )
    try:
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert cancelled.is_set() and record.phase == "storage-unknown"
        release.set()
        result = await session.confirm_recording_save(
            "original-human",
            "original-recording",
            before_read=allowed,
            reconcile=reader,
        )
        assert result["storageStatus"] == "saved" and len(writes) == 1
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        page.finish()


async def test_confirmation_has_original_twenty_second_read_bound():
    session, record, page, writes = await unknown()
    cancelled = asyncio.Event()

    async def reader(payload, digest):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    started = asyncio.get_running_loop().time()
    try:
        with pytest.raises(ControlError, match="^browser_recording_write_unconfirmed$"):
            await session.confirm_recording_save(
                "original-human",
                "original-recording",
                before_read=allowed,
                reconcile=reader,
            )
        assert asyncio.get_running_loop().time() - started >= 20
        assert cancelled.is_set() and len(writes) == 1
        assert record.phase == "storage-unknown"
    finally:
        page.finish()


@pytest.mark.parametrize("phase", ["recording", "pending-save", "event-unknown"])
async def test_confirmation_cannot_submit_or_wait_for_a_terminal_write(phase):
    entered, release = asyncio.Event(), asyncio.Event()
    writes = []

    async def persist(payload):
        writes.append(payload)
        entered.set()
        await release.wait()

    record, page, _, _ = await active(persist)
    pending = None
    try:
        if phase == "pending-save":
            pending = asyncio.create_task(
                record.finish("original-human", before_read=allowed)
            )
            await entered.wait()
        elif phase == "event-unknown":
            # An uncertain event checkpoint never submitted terminal bytes.
            record.phase = "storage-unknown"
        with pytest.raises(ControlError, match="^browser_recording_write_unconfirmed$"):
            await record.confirm_saved(
                "original-human", before_read=allowed, reconcile=allowed
            )
        assert len(writes) == (1 if phase == "pending-save" else 0)
    finally:
        release.set()
        if pending is not None:
            await pending
        else:
            record.phase = "recording"
            await record.interrupt()
        page.finish()


async def test_original_installed_reader_is_used_without_a_replacement_capability():
    session, record, page, writes = await unknown()
    reads = []

    async def original_reader(payload, digest):
        assert payload == writes[0]
        reads.append(digest)

    record.reconcile = original_reader
    try:
        result = await session.confirm_recording_save(
            "original-human",
            "original-recording",
            before_read=allowed,
        )
        assert result["storageStatus"] == "saved" and len(reads) == len(writes) == 1
    finally:
        page.finish()
