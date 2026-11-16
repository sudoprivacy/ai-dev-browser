"""Original Worker agent argument checks shared with admitted host callers.

These are codecs, not authorization. A selected session still needs its
original control epochs and current host assertion before execution.
"""

import json
from typing import Any, cast

from .control import ControlError


def agent_epochs(action: dict[str, Any]) -> tuple[int, int]:
    values = action.get("controlEpoch"), action.get("targetEpoch")
    if any(type(value) is not int or value < 0 for value in values):
        raise ControlError("invalid_browser_epoch")
    return cast(tuple[int, int], values)


def command_parts(action: dict[str, Any]) -> tuple[str, dict[str, Any], str | None]:
    method, params = action.get("method"), action.get("params", {})
    frame = action.get("frame")
    if frame is not None and (
        not isinstance(frame, str) or not frame or len(frame) > 8192
    ):
        raise ControlError("invalid_browser_frame")
    # Page commands stay on the selected target. Browser/Target/remote
    # endpoint commands are owned by the session lifecycle instead.
    if (
        not isinstance(method, str)
        or method
        not in {
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
        }
        or not isinstance(params, dict)
    ):
        raise ControlError("invalid_browser_command")
    return method, params, frame


def mcp_action(arguments: dict[str, Any]) -> dict[str, Any]:
    if arguments.get("kind") == "command":
        raw_params = arguments.get("paramsJson", "{}")
        if not isinstance(raw_params, str) or len(raw_params) > 262144:
            raise ControlError("invalid_browser_command")
        try:
            command_params = json.loads(raw_params)
        except ValueError:
            raise ControlError("invalid_browser_command") from None
        arguments = {**arguments, "params": command_params}
    return arguments
