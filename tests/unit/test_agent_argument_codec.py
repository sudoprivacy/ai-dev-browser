"""Original Worker checks, without constructing a substitute Worker/binding."""

import pytest

from ai_dev_browser.remote.agent import agent_epochs, command_parts, mcp_action
from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.worker import Worker


@pytest.mark.parametrize(
    "method",
    [
        "Page.getLayoutMetrics",
        "Page.captureScreenshot",
        "Page.reload",
        "Page.getNavigationHistory",
        "Page.navigateToHistoryEntry",
        "Runtime.evaluate",
        "Runtime.callFunctionOn",
        "Runtime.getProperties",
        "DOM.getDocument",
        "DOM.getFlattenedDocument",
        "DOM.describeNode",
        "DOM.querySelector",
        "DOM.querySelectorAll",
        "DOM.getBoxModel",
        "DOM.getContentQuads",
        "DOM.getAttributes",
        "DOM.getOuterHTML",
        "DOM.focus",
        "DOM.scrollIntoViewIfNeeded",
        "Input.dispatchMouseEvent",
        "Input.dispatchKeyEvent",
        "Input.insertText",
        "Accessibility.getFullAXTree",
        "Accessibility.getPartialAXTree",
    ],
)
def test_original_page_method_and_frame_arguments_are_retained(method):
    action = mcp_action(
        {
            "kind": "command",
            "method": method,
            "paramsJson": '{"original":"中文"}',
            "frame": "original-frame",
        }
    )
    assert command_parts(action) == (method, {"original": "中文"}, "original-frame")
    assert action["paramsJson"] == '{"original":"中文"}'


@pytest.mark.parametrize(
    "method",
    [
        "Browser.close",
        "Target.createTarget",
        "Target.attachToTarget",
        "Network.getAllCookies",
        "Page.navigate",
        "Runtime.runIfWaitingForDebugger",
        "",
        None,
        True,
    ],
)
def test_lifecycle_endpoint_and_unapproved_methods_remain_refused(method):
    with pytest.raises(ControlError, match="^invalid_browser_command$"):
        command_parts({"method": method})


@pytest.mark.parametrize(
    "frame",
    ["", False, 1, {}, [], "f" * 8193],
    ids=["empty", "boolean", "number", "object", "array", "overlimit"],
)
def test_original_frame_shape_bound_is_preserved(frame):
    with pytest.raises(ControlError, match="^invalid_browser_frame$"):
        command_parts({"method": "Runtime.evaluate", "frame": frame})


@pytest.mark.parametrize(
    "params",
    ["{", "", False, {}, "x" * 262145],
    ids=["broken", "empty", "boolean", "object", "overlimit"],
)
def test_original_json_decoder_refuses_invalid_or_unbounded_text(params):
    with pytest.raises(ControlError, match="^invalid_browser_command$"):
        mcp_action({"kind": "command", "paramsJson": params})


@pytest.mark.parametrize("params", ["null", "[]", "true", "1", '"string"'])
def test_valid_json_that_is_not_command_object_is_not_accepted(params):
    action = mcp_action(
        {"kind": "command", "method": "Runtime.evaluate", "paramsJson": params}
    )
    with pytest.raises(ControlError, match="^invalid_browser_command$"):
        command_parts(action)


@pytest.mark.parametrize("epoch,target", [(0, 0), (1, 7), (2**40, 2**41)])
def test_worker_and_host_share_the_original_epoch_validator(epoch, target):
    action = {"controlEpoch": epoch, "targetEpoch": target}
    assert agent_epochs(action) == Worker.epochs(action) == (epoch, target)


@pytest.mark.parametrize(
    "epoch,target",
    [(None, 0), (0, None), (-1, 0), (0, -1), (True, 0), (0, False), (1.0, 0), (0, "1")],
)
def test_epoch_requests_cannot_substitute_booleans_or_missing_values(epoch, target):
    action = {"controlEpoch": epoch, "targetEpoch": target}
    for validate in (agent_epochs, Worker.epochs):
        with pytest.raises(ControlError, match="^invalid_browser_epoch$"):
            validate(action)


def test_noncommand_input_stays_exact_and_decoder_confers_no_authorization():
    action = {
        "kind": "input",
        "controlEpoch": 7,
        "targetEpoch": 9,
        "input": {"kind": "text", "text": "original"},
    }
    assert mcp_action(action) is action
