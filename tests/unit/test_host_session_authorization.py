"""Current host grants fence session reads as well as human input."""

import asyncio
from types import SimpleNamespace

import pytest

from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.session import BrowserSession


@pytest.mark.parametrize("during_drag", [False, True])
async def test_frame_withdrawal_after_capture_withholds_pixels(during_drag):
    entered, release = asyncio.Event(), asyncio.Event()
    allowed = True
    captures = []

    async def check():
        if not allowed:
            raise PermissionError("original grant revoked")

    class Page:
        disconnected = False

        async def close(self):
            self.disconnected = True

        async def call(self, method, params=None):
            if method == "Page.getLayoutMetrics":
                return {"cssLayoutViewport": {"clientWidth": 640, "clientHeight": 480}}
            assert method == "Page.captureScreenshot"
            captures.append(True)
            entered.set()
            await release.wait()
            return {"data": "withheld pixels"}

    session = BrowserSession(SimpleNamespace(_automation_target_id="page"), None)
    session._page = Page()
    await session.attach("viewer")
    task = asyncio.create_task(
        session.frame("viewer", 0, 0, during_drag=during_drag, before_effect=check)
    )
    await entered.wait()
    allowed = False
    release.set()
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await task
    assert captures == [True]
    assert session._frame is None
    await session.close()


async def test_state_withdrawal_after_target_refresh_withholds_tabs():
    allowed = True

    async def check():
        if not allowed:
            raise PermissionError("original grant revoked")

    class Browser:
        _automation_target_id = "page"
        tabs = []

        async def update_targets(self):
            nonlocal allowed
            self.tabs = [
                SimpleNamespace(
                    _target=SimpleNamespace(
                        target_id="page",
                        title="private",
                        url="https://private.example/",
                    )
                )
            ]
            allowed = False

    session = BrowserSession(Browser(), None)
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await session.state(before_effect=check)


async def test_queued_selection_is_not_submitted_after_revoke(monkeypatch):
    session = BrowserSession(SimpleNamespace(_automation_target_id="page"), None)
    await session.control.take("user")
    allowed, selections = True, []

    async def check():
        if not allowed:
            raise PermissionError("original grant revoked")

    async def select(*args):
        selections.append(True)
        return "private selection"

    monkeypatch.setattr("ai_dev_browser.remote.page.PageView.selection", select)
    await session.control._operations.acquire()
    pending = asyncio.create_task(session.selection("user", 1, 0, before_effect=check))
    await asyncio.sleep(0)
    allowed = False
    session.control._operations.release()
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await pending
    assert selections == []


async def test_session_take_and_return_keep_the_same_current_assertion():
    session = BrowserSession(SimpleNamespace(_automation_target_id="page"), None)
    allowed, observations = True, []

    async def check():
        if not allowed:
            raise PermissionError("original grant revoked")

    async def observe():
        nonlocal allowed
        observations.append(True)
        allowed = False
        return {"image": "private"}

    session._observe = observe
    assert (await session.take("user", 0, 0, before_effect=check))["state"] == "human"
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await session.give_back("user", 1, 0, before_effect=check)
    assert observations == [True]
    assert session.control.state == "human"
    assert session.control.controller == "user"
