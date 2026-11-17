"""Actual Chrome/input/fsync; current reader and writer are explicit host fixtures."""

import asyncio
import hashlib
import json
import os

import aiohttp
import pytest

from ai_dev_browser.core.connection import BrowserClient, get_active_tab
from ai_dev_browser.core.navigation import page_goto
from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.session import BrowserSession
from tests.integration.semantic_event_sink_support import (
    current_fixture,
    QUERY,
    SECRET,
    submit_original_form,
)
from tests.integration.test_recording_event_sink_live import incremental_site
from tests.integration.test_remote_view import wait_for
from tests.integration.test_session_operations_live import owned_operations_browser

confirmation_browser = owned_operations_browser
confirmation_site = incremental_site


async def confirmation_journey(browser, tmp_path, website):
    origin, receipts = website
    await page_goto(await get_active_tab(browser), origin)
    saved = tmp_path / "original-terminal.json"
    writes, reads = [], []
    current_reader = True
    hold_read = False
    entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def reader_grant():
        if not current_reader:
            raise PermissionError("fixture original reader disabled")

    async def persist(payload):
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        assert SECRET.encode() not in raw
        with saved.open("xb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        writes.append(hashlib.sha256(raw).hexdigest())
        raise ConnectionError("actual fsync succeeded; fixture reply was lost")

    async def reconcile(payload, digest):
        await reader_grant()
        reads.append(digest)
        if hold_read:
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
        raw = saved.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest == writes[0]
        assert json.loads(raw) == payload
        await reader_grant()

    async with aiohttp.ClientSession() as http:
        session = BrowserSession(browser, http)
        await session.state(before_effect=current_fixture)
        await session.control.take("original-human", before_effect=current_fixture)
        page = await session._connect_page()
        original_reader, original_target = page.reader, session.target_id
        await session.attach("original-viewer", before_effect=current_fixture)
        closed = False

        async def frame_grant(target, frame, context, unique, source_origin):
            assert target == original_target and source_origin == origin
            assert frame and type(context) is int and unique
            return current_fixture

        async def confirm():
            return await session.confirm_recording_save(
                "original-human",
                "original-save",
                before_read=reader_grant,
            )

        try:
            await session.start_recording(
                "original-human",
                session.control.epoch,
                session.control.target_epoch,
                "original-save",
                before_effect=current_fixture,
                authorize_frame=frame_grant,
                before_read=reader_grant,
                persist=persist,
                reconcile=reconcile,
            )
            await submit_original_form(session, page)

            async def submitted():
                return receipts

            await wait_for(submitted, lambda rows: len(rows) == 1)
            assert receipts[0]["query"] == QUERY and receipts[0]["trusted"] is True
            with pytest.raises(
                ControlError, match="^browser_recording_write_unconfirmed$"
            ):
                await session.stop_recording(
                    "original-human",
                    session.control.epoch,
                    session.control.target_epoch,
                    before_effect=current_fixture,
                    before_read=reader_grant,
                )
            original_bytes = saved.read_bytes()
            terminal = json.loads(original_bytes)
            assert terminal["recordingId"] == "original-save"
            assert terminal["status"] == "stopped" and terminal["draft"]
            assert any(
                event.get("value") == QUERY for event in terminal["snapshot"]["events"]
            )
            assert SECRET not in original_bytes.decode()

            # Default Close never installs or silently uses a completion reader.
            with pytest.raises(
                ControlError, match="^browser_recording_write_unconfirmed$"
            ):
                await session.close()
            assert not original_reader.done() and "original-viewer" in session._viewers
            assert reads == [] and len(writes) == 1

            async with (
                session.control._operations
            ):  # The actual host lifecycle barrier.
                current_reader = False
                with pytest.raises(
                    ControlError, match="^browser_authorization_denied$"
                ):
                    await confirm()
                assert reads == [] and not original_reader.done()
                current_reader = True
                with pytest.raises(ControlError, match="^browser_recording_not_owned$"):
                    await session.confirm_recording_save(
                        "original-human",
                        "replacement-id",
                        before_read=reader_grant,
                    )
                assert reads == []

                hold_read = True
                pending = asyncio.create_task(confirm())
                try:
                    await asyncio.wait_for(entered.wait(), 10)
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                finally:
                    release.set()
                    await asyncio.gather(pending, return_exceptions=True)
                assert cancelled.is_set() and len(writes) == 1
                with pytest.raises(
                    ControlError, match="^browser_recording_write_unconfirmed$"
                ):
                    await session.close()
                assert (
                    not original_reader.done() and session.target_id == original_target
                )

                hold_read = False
                result = await asyncio.wait_for(confirm(), 10)
                assert result["storageStatus"] == "saved" and result["hasDraft"]
                assert result["recordingId"] == "original-save"
                await confirm()  # A confirmed save doesn't need another store read.
                assert len(reads) == 2 and len(writes) == 1
                assert saved.read_bytes() == original_bytes
                await session.close()
                closed = True
                assert original_reader.done() and not session._viewers

            (tmp_path / "original-save-close-evidence.json").write_text(
                json.dumps(
                    {
                        "recordingId": result["recordingId"],
                        "terminalWrites": len(writes),
                        "terminalSha256": writes[0],
                        "storeReads": len(reads),
                        "realBrowserSubmissions": len(receipts),
                        "defaultCloseRefused": True,
                        "withdrawnReaderRefused": True,
                        "cancelledReadRetainedOriginal": True,
                        "callerHeldBarrier": True,
                        "originalTargetRetained": True,
                        "originalReaderClosedAfterConfirmation": original_reader.done(),
                        "productionAuthority": False,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        finally:
            if not closed:
                current_reader, hold_read = True, False
                release.set()
                if saved.exists():
                    await confirm()
                await session.close()


async def test_original_save_read_confirmation_allows_owned_close_without_repeat_write(
    confirmation_browser,
    confirmation_site,
    tmp_path,
):
    await confirmation_journey(confirmation_browser, tmp_path, confirmation_site)


async def test_extension_original_save_read_confirmation_preserves_native_session(
    live_extension,
    confirmation_site,
    tmp_path,
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
        await confirmation_journey(browser, tmp_path, confirmation_site)
    finally:
        await browser.close()
