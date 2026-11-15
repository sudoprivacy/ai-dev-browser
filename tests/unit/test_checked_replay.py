"""Replay operation/lease/parameter boundaries; live SDK actuation is separate."""

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from ai_dev_browser.record.replay import CheckedReplay, match_current_target
from ai_dev_browser.remote.control import BrowserControl, ControlError


async def allowed():
    return None


class Grants:
    def __init__(self):
        self.allowed = True
        self.requests = []

    async def __call__(self, recording, step, target, frame):
        self.requests.append((recording, copy.deepcopy(step), target, frame))

        async def current():
            if not self.allowed:
                raise PermissionError("private original grant")

        return current


def original_document(**changes):
    return {
        "schemaVersion": "1.0",
        "recordingId": "original-recording",
        "inputs": [{"name": "query", "required": True}],
        "steps": [
            {
                "id": "original-step",
                "kind": "fill",
                "value": "{{query}}",
                "target": {
                    "name": "Search",
                    "role": "textbox",
                    "targetId": "old-target",
                },
            }
        ],
        **changes,
    }


def runner(grants=None):
    session = SimpleNamespace(control=BrowserControl(), target_id="current-target")
    return CheckedReplay(
        session,
        "original-operation",
        actor="ai",
        control_epoch=0,
        target_epoch=0,
        target_bindings={"old-target": "current-target"},
        authorize_step=grants or Grants(),
    )


def test_missing_authority_refuses_without_creating_a_session():
    with pytest.raises(ControlError, match="^browser_authorization_required$"):
        CheckedReplay(
            None,
            "original",
            actor="ai",
            control_epoch=0,
            target_epoch=0,
            target_bindings={},
            authorize_step=None,
        )


@pytest.mark.parametrize(
    "recorded,current",
    [
        ({"name": "Password"}, {"name": "Email"}),
        ({"type": "password"}, {"type": "email"}),
        ({"tag": "textarea"}, {"tag": "input"}),
    ],
)
def test_reused_native_id_cannot_override_changed_field_meaning(recorded, current):
    with pytest.raises(ControlError, match="^browser_replay_target_not_found$"):
        match_current_target(
            {"id": "field", "role": "textbox", **recorded},
            [{"ref": "1#123", "id": "field", "role": "textbox", **current}],
        )


@pytest.mark.parametrize(
    "elements,code",
    [
        (
            [{"ref": "7", "name": "Search", "role": "textbox"}],
            "browser_replay_target_not_found",
        ),
        (
            [
                {"ref": "1#101", "name": "Search", "role": "textbox"},
                {"ref": "2#202", "name": "Search", "role": "textbox"},
            ],
            "browser_replay_target_ambiguous",
        ),
        (
            [{"ref": "1#101", "name": "Search", "role": "button"}],
            "browser_replay_target_not_found",
        ),
        (
            [{"ref": "1#101", "name": "Search", "role": "textbox", "disabled": True}],
            "browser_replay_target_not_found",
        ),
    ],
)
def test_current_matching_never_uses_legacy_index_or_tied_first_match(elements, code):
    with pytest.raises(ControlError, match="^" + code + "$"):
        match_current_target(
            {
                "name": "Search",
                "role": "textbox",
                "ref": "old#99",
                "bbox": {"x": 1, "y": 2},
            },
            elements,
        )


def test_current_unique_match_retains_the_actual_sdk_backend_reference():
    assert (
        match_current_target(
            {"id": "actual", "role": "button"},
            [
                {"ref": "1#101", "id": "different", "role": "button"},
                {"ref": "2#202", "id": "actual", "role": "button"},
            ],
        )
        == "2#202"
    )


@pytest.mark.parametrize(
    "change,inputs,code",
    [
        ({}, {}, "browser_replay_input_required"),
        ({}, {"query": "ok", "extra": "secret"}, "browser_replay_input_invalid"),
        (
            {"steps": [{"id": "1", "kind": "eval", "value": 'fetch("/write")'}]},
            {"query": "ok"},
            "browser_replay_step_invalid",
        ),
        (
            {"steps": [{"id": "1", "kind": "open", "url": "javascript:alert(1)"}]},
            {"query": "ok"},
            "invalid_browser_url",
        ),
        (
            {
                "steps": [
                    {
                        "id": "1",
                        "kind": "upload",
                        "target": {"name": "File"},
                        "value": '["C:/private/file"]',
                    }
                ]
            },
            {"query": "ok"},
            "browser_files_invalid_selection",
        ),
        (
            {"verification": [{"type": "arbitrary-eval", "value": "true"}]},
            {"query": "ok"},
            "browser_replay_verification_invalid",
        ),
        (
            {
                "steps": [
                    {"id": "same", "kind": "press", "key": "Enter"},
                    {"id": "same", "kind": "press", "key": "Enter"},
                ]
            },
            {"query": "ok"},
            "browser_replay_step_invalid",
        ),
    ],
)
async def test_entire_document_and_required_parameters_are_checked_before_effect(
    change, inputs, code
):
    replay = runner()
    with pytest.raises(ControlError, match="^" + code + "$"):
        await replay.run(
            original_document(**change),
            inputs,
            before_run=allowed,
            before_result=allowed,
        )
    assert replay.status()["steps"] == []


async def test_original_operation_is_single_use_inputs_private_and_snapshot_immutable(
    monkeypatch,
):
    grants = Grants()
    replay = runner(grants)
    document = original_document()
    before = copy.deepcopy(document)
    effects = []

    async def perform(recording, step, assertion):
        await assertion()
        effects.append(step.value)
        replay._sent = True
        replay._any_effect = True

    monkeypatch.setattr(replay, "_perform", perform)
    result = await replay.run(
        document,
        {"query": "PRIVATE_PARAMETER"},
        before_run=allowed,
        before_result=allowed,
    )
    assert (
        result["status"] == "passed" and result["operationId"] == "original-operation"
    )
    assert effects == ["PRIVATE_PARAMETER"] and document == before
    assert "PRIVATE_PARAMETER" not in json.dumps(result)
    with pytest.raises(ControlError, match="^browser_replay_already_submitted$"):
        await replay.run(
            document,
            {"query": "PRIVATE_PARAMETER"},
            before_run=allowed,
            before_result=allowed,
        )
    assert len(effects) == 1


async def test_queued_replay_rechecks_original_grant_before_effect(monkeypatch):
    grants = Grants()
    replay = runner(grants)
    effects = []

    async def perform(*args):
        effects.append("input")

    monkeypatch.setattr(replay, "_perform", perform)
    await replay.session.control._operations.acquire()
    pending = asyncio.create_task(
        replay.run(
            original_document(),
            {"query": "value"},
            before_run=allowed,
            before_result=allowed,
        )
    )
    while not grants.requests:
        await asyncio.sleep(0)
    grants.allowed = False
    replay.session.control._operations.release()
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await pending
    assert effects == [] and replay.status()["status"] == "failed"


async def test_human_takeover_does_not_silently_grant_ai_replay(monkeypatch):
    replay = runner()
    await replay.session.control.take("original-human")
    effects = []

    async def perform(*args):
        effects.append("input")

    monkeypatch.setattr(replay, "_perform", perform)
    with pytest.raises(ControlError, match="^stale_browser_operation$"):
        await replay.run(
            original_document(),
            {"query": "value"},
            before_run=allowed,
            before_result=allowed,
        )
    assert not effects and replay.session.control.controller == "original-human"
    assert replay.session.control.state == "human"


async def test_post_effect_failure_and_withheld_result_keep_original_operation(
    monkeypatch,
):
    replay = runner()
    calls = []

    async def perform(*args):
        calls.append("one actual submission fixture")
        replay._sent = True
        replay._any_effect = True
        raise ConnectionError("private transport detail")

    monkeypatch.setattr(replay, "_perform", perform)
    with pytest.raises(ControlError, match="^browser_replay_write_unconfirmed$"):
        await replay.run(
            original_document(),
            {"query": "value"},
            before_run=allowed,
            before_result=allowed,
        )
    assert len(calls) == 1 and replay.status()["operationId"] == "original-operation"
    assert replay.status()["status"] == "unconfirmed"
    assert "private transport" not in json.dumps(replay.status())


async def test_real_cancellation_drains_the_existing_control_barrier(monkeypatch):
    replay = runner()
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def perform(*args):
        replay._sent = True
        replay._any_effect = True
        calls.append("one")
        entered.set()
        await release.wait()

    monkeypatch.setattr(replay, "_perform", perform)
    pending = asyncio.create_task(
        replay.run(
            original_document(),
            {"query": "value"},
            before_run=allowed,
            before_result=allowed,
        )
    )
    await entered.wait()
    pending.cancel()
    await asyncio.sleep(0)
    assert not pending.done() and replay.session.control._operations.locked()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert calls == ["one"] and replay.status()["status"] == "cancelled"
    assert replay.status()["possibleEffect"] is True


def test_original_scroll_and_recorded_search_transition_parameter_semantics():
    doc = original_document(
        steps=[
            {"id": "scroll", "kind": "scroll_to", "value": "0.000,128.000"},
            {
                "id": "results",
                "kind": "navigate",
                "url": "https://www.baidu.com/s?wd=old&keep=1",
            },
        ]
    )
    _, steps = runner()._plan(doc, {"query": "new query & value"})
    assert steps[0].value == "0.000,128.000"
    assert "wd=new+query+%26+value" in steps[1].url and "keep=1" in steps[1].url
    _, literal = runner()._plan(
        original_document(), {"query": "literal {{new_template}} data"}
    )
    assert literal[0].value == "literal {{new_template}} data"


async def test_native_security_origin_is_not_reconstructed_from_a_page_url():
    class Page:
        async def call(self, *args):
            return {
                "frameTree": {
                    "frame": {
                        "id": "root",
                        "url": "https://host.example/",
                        "loaderId": "current",
                        "securityOrigin": "https://host.example",
                    },
                    "childFrames": [
                        {
                            "frame": {
                                "id": "opaque",
                                "url": "https://other.example/",
                                "loaderId": "child",
                                "securityOrigin": "null",
                            }
                        }
                    ],
                }
            }

    replay = runner()
    actual = await replay._frame(Page(), {"framePath": ["null"]})
    assert actual["id"] == "opaque" and actual["origin"] == "null"
    with pytest.raises(ControlError, match="^browser_replay_frame_ambiguous$"):
        await replay._frame(Page(), {"framePath": ["https://other.example"]})
