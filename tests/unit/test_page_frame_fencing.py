"""Pixels captured across a lease change must not be relabelled or cached."""

import asyncio
from types import SimpleNamespace

import pytest

from ai_dev_browser.remote.control import BrowserControl, ControlError
from ai_dev_browser.remote.session import BrowserSession


@pytest.mark.parametrize("changed", ["lease", "target", "viewer"])
async def test_inflight_drag_frame_cannot_publish_after_ownership_changes(changed):
    entered, release = asyncio.Event(), asyncio.Event()
    control = BrowserControl()
    await control.take("user-reviewer")

    class Page:
        disconnected = False

        async def call(self, method, params=None):
            if method == "Page.getLayoutMetrics":
                return {"cssLayoutViewport": {"clientWidth": 640, "clientHeight": 480}}
            assert method == "Page.captureScreenshot"
            entered.set()
            await release.wait()
            return {"data": "pixels-from-old-page"}

    session = BrowserSession(
        SimpleNamespace(_automation_target_id="page"), None, control=control
    )
    session._page = Page()
    await session.attach("viewer")
    frame = asyncio.create_task(
        session.frame("viewer", control.epoch, control.target_epoch, during_drag=True)
    )
    await entered.wait()
    if changed == "lease":
        control.epoch += 1
    elif changed == "target":
        control.change_target()
    else:
        await session.detach("viewer")
    release.set()
    with pytest.raises(
        ControlError, match="stale_browser_operation|browser_viewer_not_attached"
    ):
        await frame
    assert session._frame is None
    assert control.state == "human" and control.controller == "user-reviewer"


async def test_motion_during_capture_cannot_restore_a_stale_frame_cache():
    entered, release = asyncio.Event(), asyncio.Event()

    class Page:
        disconnected = False
        captures = 0

        async def call(self, method, params=None):
            if method == "Page.getLayoutMetrics":
                return {"cssLayoutViewport": {"clientWidth": 640, "clientHeight": 480}}
            assert method == "Page.captureScreenshot"
            self.captures += 1
            if self.captures == 1:
                entered.set()
                await release.wait()
                return {"data": "old"}
            return {"data": "new"}

    session = BrowserSession(SimpleNamespace(_automation_target_id="page"), None)
    session._page = Page()
    await session.attach("viewer")
    frame = asyncio.create_task(session.frame("viewer", 0, 0, during_drag=True))
    await entered.wait()
    session.invalidate_frame()
    release.set()
    assert (await frame)["data"] == "old"
    assert session._frame is None
    assert (await session.frame("viewer", 0, 0, during_drag=True))["data"] == "new"
