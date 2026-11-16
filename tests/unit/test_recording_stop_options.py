"""Original Mosswork stop options remain fixed on first persistence."""

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_semantic_capture import allowed
from test_session_recording import active

from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.session import BrowserSession
from ai_dev_browser.remote.worker import Worker


async def test_capture_only_stop_does_not_generate_a_draft_or_regenerate_on_repeat(
    monkeypatch,
):
    def unexpected(*args, **kwargs):
        raise AssertionError("draft generation was not requested")

    monkeypatch.setattr(
        "ai_dev_browser.record.session.build_recording_draft", unexpected
    )
    record, page, _, written = await active()
    page.pending_input = "original last value"
    result = await record.finish(
        "original-human", before_read=allowed, generate_steps=False
    )
    assert result["storageStatus"] == "saved" and result["hasDraft"] is False
    assert written[0]["snapshot"]["events"][-1]["value"] == "original last value"
    assert written[0]["draft"] is None
    assert written[0]["draftError"] == "browser_recording_draft_not_requested"
    await record.finish(
        "original-human", before_read=allowed, generate_steps=True, skill_name="later"
    )
    assert len(written) == 1
    page.finish()


async def test_first_stop_skill_name_remains_original_after_unknown_and_reconciliation():
    writes = []

    async def lost(payload):
        writes.append(copy.deepcopy(payload))
        raise ConnectionError("owned synthetic commit reply lost")

    record, page, _, _ = await active(lost)
    with pytest.raises(ControlError, match="browser_recording_write_unconfirmed"):
        await record.finish(
            "original-human", before_read=allowed, skill_name="Original Chosen Workflow"
        )

    async def reconcile(payload, digest):
        assert writes == [payload]
        assert "name: original-chosen-workflow" in payload["draft"]["skillDraft"]

    result = await record.finish(
        "original-human",
        before_read=allowed,
        reconcile=reconcile,
        generate_steps=False,
        skill_name="different",
    )
    assert result["storageStatus"] == "saved" and result["hasDraft"] is True
    assert len(writes) == 1
    page.finish()


@pytest.mark.parametrize("option", [None, "false", 0, []])
async def test_malformed_generation_option_leaves_capture_and_store_untouched(option):
    record, page, _, written = await active()
    with pytest.raises(ControlError, match="invalid_browser_recording_options"):
        await record.finish(
            "original-human", before_read=allowed, generate_steps=option
        )
    assert written == [] and record.phase == "recording" and page.handlers
    await record.finish("original-human", before_read=allowed)
    page.finish()


@pytest.mark.parametrize("option", [False, 17, {}])
async def test_malformed_skill_name_never_stops_or_saves_capture(option):
    record, page, _, written = await active()
    with pytest.raises(ControlError, match="invalid_browser_recording_options"):
        await record.finish("original-human", before_read=allowed, skill_name=option)
    assert written == [] and record.phase == "recording"
    await record.finish("original-human", before_read=allowed)
    page.finish()


@pytest.mark.parametrize("generate", [False, True])
async def test_existing_worker_forwards_original_stop_choices_without_new_endpoint(
    tmp_path, generate
):
    worker = Worker(tmp_path, "host-fixture", "agent-fixture")
    stop = AsyncMock(return_value={"storageStatus": "saved"})
    worker.session = SimpleNamespace(
        _recording=SimpleNamespace(capture=SimpleNamespace(recording_id="original")),
        stop_recording=stop,
    )
    worker.state = AsyncMock(return_value={"state": "fixture"})
    await worker.invoke(
        "user-fixture",
        {
            "kind": "record-stop",
            "recordingId": "original",
            "controlEpoch": 0,
            "targetEpoch": 0,
            "generateSteps": generate,
            "name": "Original Workflow",
        },
        before_effect=allowed,
        recording_hooks={"read": allowed},
    )
    stop.assert_awaited_once_with(
        "user-fixture",
        0,
        0,
        before_effect=allowed,
        before_read=allowed,
        reconcile=None,
        generate_steps=generate,
        skill_name="Original Workflow",
    )


async def test_record_status_does_not_accept_stop_options(tmp_path):
    worker = Worker(tmp_path, "host-fixture", "agent-fixture")
    worker.session = SimpleNamespace(
        _recording=SimpleNamespace(capture=SimpleNamespace(recording_id="original"))
    )
    with pytest.raises(ControlError, match="invalid_browser_request"):
        await worker.invoke(
            "user-fixture",
            {
                "kind": "record-status",
                "recordingId": "original",
                "controlEpoch": 0,
                "targetEpoch": 0,
                "generateSteps": False,
            },
            before_effect=allowed,
        )


async def test_existing_session_stop_reaches_actual_coordinator_with_original_choices():
    record, page, _, written = await active()
    session = BrowserSession(
        SimpleNamespace(_automation_target_id="original-target", transport=None), None
    )
    session._recording = record
    result = await session.stop_recording(
        "original-human",
        0,
        0,
        before_effect=allowed,
        before_read=allowed,
        generate_steps=False,
        skill_name="Original Workflow",
    )
    assert result["storageStatus"] == "saved" and written[0]["draft"] is None
    assert written[0]["draftError"] == "browser_recording_draft_not_requested"
    page.finish()
