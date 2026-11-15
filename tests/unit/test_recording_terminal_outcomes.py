"""Original recording write uncertainty at cleanup and result release."""

import asyncio

import pytest

from ai_dev_browser.remote.control import ControlError
from test_semantic_capture import allowed
from test_session_recording import active


async def test_cleanup_waiting_on_failed_original_sink_preserves_write_outcome():
    entered, release = asyncio.Event(), asyncio.Event()

    async def sink(payload):
        entered.set()
        await release.wait()
        raise ConnectionError("private original write outcome")

    record, page, _, _ = await active(sink)
    stop = asyncio.create_task(record.finish("original-human", before_read=allowed))
    await entered.wait()
    cleanup = asyncio.create_task(record.interrupt())
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(ControlError, match="^browser_recording_write_unconfirmed$"):
        await stop
    with pytest.raises(ControlError, match="^browser_recording_write_unconfirmed$"):
        await cleanup
    assert (
        record.phase == "storage-unknown"
        and record.capture.recording_id == "original-recording"
    )
    page.finish()


async def test_saved_then_withdrawn_stop_reply_is_unconfirmed_without_repeating_save():
    grants = {"allowed": True}
    writes = []

    async def current():
        if not grants["allowed"]:
            raise PermissionError("original reply grant withdrawn")

    async def sink(payload):
        writes.append(payload)
        grants["allowed"] = False

    record, page, _, _ = await active(sink)
    with pytest.raises(ControlError, match="^browser_recording_write_unconfirmed$"):
        await record.finish("original-human", before_read=current)
    assert record.phase == "saved" and len(writes) == 1
    assert (await record.finish("original-human", before_read=allowed))[
        "storageStatus"
    ] == "saved"
    assert len(writes) == 1
    page.finish()


@pytest.mark.parametrize("observer", ["second-stop", "cleanup"])
async def test_cancelled_concurrent_observer_drains_original_save(observer):
    entered, release = asyncio.Event(), asyncio.Event()
    writes = []

    async def sink(payload):
        entered.set()
        await release.wait()
        writes.append(payload)

    record, page, _, _ = await active(sink)
    first = asyncio.create_task(record.finish("original-human", before_read=allowed))
    await entered.wait()
    second = asyncio.create_task(
        record.finish("original-human", before_read=allowed)
        if observer == "second-stop"
        else record.interrupt()
    )
    try:
        await asyncio.sleep(0)
        second.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not second.done() and record.phase == "pending-save"
        release.set()
        await first
        with pytest.raises(asyncio.CancelledError):
            await second
        assert record.phase == "saved" and len(writes) == 1
        await record.finish("original-human", before_read=allowed)
        assert len(writes) == 1
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)
        page.finish()
