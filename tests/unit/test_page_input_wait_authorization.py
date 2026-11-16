"""Current public session action; page and host grant are explicit fixtures."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_dev_browser.remote.session as implementation
from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.session import BrowserSession


@pytest.mark.parametrize("withdraw", ["before", "focus", "never"])
async def test_input_authorization_after_original_focus_wait(withdraw, tmp_path):
    # Regular source qualification, no product install/PYTHONPATH/module patch.
    expected = Path(__file__).resolve().parents[2] / "ai_dev_browser/remote/session.py"
    assert Path(implementation.__file__).resolve() == expected
    allowed = withdraw != "before"
    sent = []

    async def current():
        if not allowed:
            raise PermissionError("explicit original input grant withdrawn")

    class Page:
        disconnected = False

        async def call(self, method, params=None, timeout=20):
            nonlocal allowed
            sent.append({"method": method, "params": params, "current": allowed})
            if method == "Page.getLayoutMetrics":
                return {"cssLayoutViewport": {"clientWidth": 300, "clientHeight": 200}}
            if method == "Page.bringToFront" and withdraw == "focus":
                allowed = False
            return {}

    session = BrowserSession(
        SimpleNamespace(_automation_target_id="original-target"), None
    )
    session._page = Page()
    refused = None
    try:
        await session.action(
            "ai",
            0,
            0,
            {"kind": "input", "input": {"kind": "click", "x": 20, "y": 20}},
            before_effect=current,
        )
    except ControlError as error:
        refused = error.code
    (tmp_path / "original-input-wait-observation.json").write_text(
        json.dumps(
            {
                "source": str(expected),
                "withdraw": withdraw,
                "refused": refused,
                "sent": sent,
                "sourceOnlyFixtureNoHttpNativeOrProductionEffect": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if withdraw == "never":
        assert refused is None
        assert [
            x["params"]["type"]
            for x in sent
            if x["method"] == "Input.dispatchMouseEvent"
        ] == [
            "mouseMoved",
            "mousePressed",
            "mouseReleased",
        ]
    else:
        assert refused == "browser_authorization_denied", sent
        assert not any(x["method"] == "Input.dispatchMouseEvent" for x in sent)


@pytest.mark.parametrize("boundary", ["move", "press", "target", "socket"])
async def test_input_rechecks_each_wait_but_releases_only_original_pressed_button(
    boundary,
):
    allowed, sent = True, []

    async def current():
        if not allowed:
            raise PermissionError("original current grant withdrawn")

    class Page:
        disconnected = False

        async def call(self, method, params=None, timeout=20):
            nonlocal allowed
            sent.append((self, method, params))
            if method == "Page.getLayoutMetrics":
                return {"cssLayoutViewport": {"clientWidth": 300, "clientHeight": 200}}
            if method == "Page.bringToFront":
                if boundary == "target":
                    session.control.change_target()
                elif boundary == "socket":
                    session._page = Page()
            if method == "Input.dispatchMouseEvent" and params["type"] == {
                "move": "mouseMoved",
                "press": "mousePressed",
            }.get(boundary):
                allowed = False
            return {}

    session = BrowserSession(
        SimpleNamespace(_automation_target_id="original-target"), None
    )
    original_page = Page()
    session._page = original_page
    operation = session.action(
        "ai",
        0,
        0,
        {"kind": "input", "input": {"kind": "click", "x": 20, "y": 20}},
        before_effect=current,
    )
    if boundary == "press":
        await operation
        assert [
            params["type"]
            for _, method, params in sent
            if method == "Input.dispatchMouseEvent"
        ] == [
            "mouseMoved",
            "mousePressed",
            "mouseReleased",
        ]
        assert not allowed
    else:
        expected = {
            "move": "browser_authorization_denied",
            "target": "stale_browser_operation",
            "socket": "browser_target_closed",
        }[boundary]
        with pytest.raises(ControlError, match="^" + expected + "$"):
            await operation
        assert [
            params["type"]
            for _, method, params in sent
            if method == "Input.dispatchMouseEvent"
        ] == (["mouseMoved"] if boundary == "move" else [])
    assert all(page is original_page for page, _, _ in sent)
