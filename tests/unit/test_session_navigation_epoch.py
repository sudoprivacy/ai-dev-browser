"""Navigation invalidates prior input, including uncertain and canceled sends.

The first nine cases retain PC3's original public0.60.0 counterexample.
Page/current callbacks here are fixtures; real Chrome journeys run separately.
"""

import asyncio
from types import SimpleNamespace

import pytest
from ai_dev_browser.remote.control import BrowserControl, ControlError
from ai_dev_browser.remote.session import BrowserSession

pytestmark = pytest.mark.asyncio


async def current():
    return None


class Page:
    disconnected = False

    def __init__(self, *, held=False):
        self.calls = []
        self.held = held
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.handlers = set()

    async def call(self, method, params=None):
        self.calls.append((method, params))
        if method == "Page.getNavigationHistory":
            return {"currentIndex": 1, "entries": [{"id": 1}, {"id": 2}, {"id": 3}]}
        if method == "Page.getFrameTree":
            return {
                "frameTree": {
                    "frame": {"id": "original-frame", "loaderId": "previous-document"}
                }
            }
        self.entered.set()
        if self.held:
            await self.release.wait()
        return {"frameId": "original-frame"}

    def add_event_handler(self, handler):
        self.handlers.add(handler)

    def remove_event_handler(self, handler):
        self.handlers.remove(handler)

    async def wait_navigation(self, _response, **_facts):
        return None


async def session_for(page):
    control = BrowserControl()
    await control.take("original-human", before_effect=current)
    session = BrowserSession(
        SimpleNamespace(_automation_target_id="same-original-tab"),
        None,
        control=control,
    )

    async def connect_page():
        return page

    session._connect_page = connect_page
    return session, control


@pytest.mark.parametrize("kind", ["navigate", "reload", "back", "forward"])
async def test_completed_navigation_invalidates_prior_target_version(kind):
    page = Page()
    session, control = await session_for(page)
    epoch, target = control.epoch, control.target_epoch
    action = {"kind": kind, "url": "http://127.0.0.1/original-next-document"}
    await session.action("original-human", epoch, target, action, before_effect=current)
    assert page.calls
    assert control.target_epoch > target


@pytest.mark.parametrize("kind", ["navigate", "reload", "back", "forward"])
async def test_queued_original_target_input_is_refused_after_navigation(kind):
    page = Page(held=True)
    session, control = await session_for(page)
    epoch, target = control.epoch, control.target_epoch
    effects = []

    async def old_input():
        effects.append("old-coordinate-input")

    navigation = asyncio.create_task(
        session.action(
            "original-human",
            epoch,
            target,
            {"kind": kind, "url": "http://127.0.0.1/original-next-document"},
            before_effect=current,
        )
    )
    await asyncio.wait_for(page.entered.wait(), timeout=1)
    queued = asyncio.create_task(
        control.run("original-human", epoch, target, old_input, before_effect=current)
    )
    await asyncio.sleep(0)
    assert not queued.done()
    page.release.set()
    await navigation
    with pytest.raises(ControlError, match="stale_browser_operation"):
        await queued
    assert effects == []


async def test_invalid_navigation_before_effect_keeps_original_version_and_sends_nothing():
    page = Page()
    session, control = await session_for(page)
    epoch, target = control.epoch, control.target_epoch
    with pytest.raises(ControlError, match="invalid_browser_url"):
        await session.action(
            "original-human",
            epoch,
            target,
            {"kind": "navigate", "url": "not-an-authorized-navigation-url"},
            before_effect=current,
        )
    assert control.target_epoch == target and page.calls == []


@pytest.mark.parametrize("kind", ["navigate", "reload", "back", "forward"])
async def test_uncertain_navigation_changes_version_without_resubmission(kind):
    class LostReply(Page):
        async def call(self, method, params=None):
            result = await super().call(method, params)
            if method not in ("Page.getNavigationHistory", "Page.getFrameTree"):
                raise TimeoutError("Original acknowledgement was lost")
            return result

    page = LostReply()
    session, control = await session_for(page)
    target = control.target_epoch
    session._frame = {"data": "old-frame"}
    session._file_chooser = {"id": "old-document-chooser"}
    with pytest.raises(TimeoutError, match="acknowledgement"):
        await session.action(
            "original-human",
            control.epoch,
            target,
            {"kind": kind, "url": "https://fixture.invalid/next"},
            before_effect=current,
        )
    assert control.target_epoch == target + 1
    assert session._frame is None and session._file_chooser is None
    assert (
        len(
            [
                method
                for method, _ in page.calls
                if method
                in ("Page.navigate", "Page.reload", "Page.navigateToHistoryEntry")
            ]
        )
        == 1
    )
    with pytest.raises(ControlError, match="^stale_browser_operation$"):
        await control.run("original-human", control.epoch, target, current)


@pytest.mark.parametrize("kind", ["back", "forward"])
async def test_history_without_destination_reports_no_submission_and_same_version(kind):
    class NoHistory(Page):
        async def call(self, method, params=None):
            assert method == "Page.getNavigationHistory"
            self.calls.append((method, params))
            return {"currentIndex": 0, "entries": [{"id": 1}]}

    page = NoHistory()
    session, control = await session_for(page)
    target = control.target_epoch
    result = await session.action(
        "original-human", control.epoch, target, {"kind": kind}, before_effect=current
    )
    assert result == {"navigationRequested": False, "targetEpoch": target}
    assert control.target_epoch == target and len(page.calls) == 1


async def test_protocol_navigation_error_is_not_a_successful_acknowledgement():
    class Refused(Page):
        async def call(self, method, params=None):
            self.calls.append((method, params))
            return {"errorText": "private-url network error"}

        async def wait_navigation(self, response):
            raise AssertionError("A rejected response cannot be ready")

    page = Refused()
    session, control = await session_for(page)
    target = control.target_epoch
    with pytest.raises(ControlError, match="^browser_navigation_failed$") as error:
        await session.action(
            "original-human",
            control.epoch,
            target,
            {"kind": "navigate", "url": "https://fixture.invalid/next"},
            before_effect=current,
        )
    assert "private-url" not in str(error.value)
    assert control.target_epoch == target + 1 and len(page.calls) == 1


@pytest.mark.parametrize("kind", ["navigate", "reload", "back", "forward"])
async def test_canceled_submitted_navigation_drains_and_invalidates_old_input(kind):
    page = Page(held=True)
    session, control = await session_for(page)
    epoch, target = control.epoch, control.target_epoch
    pending = asyncio.create_task(
        session.action(
            "original-human",
            epoch,
            target,
            {"kind": kind, "url": "https://fixture.invalid/next"},
            before_effect=current,
        )
    )
    await asyncio.wait_for(page.entered.wait(), 1)
    pending.cancel()
    await asyncio.sleep(0)
    assert not pending.done() and control._operations.locked()
    page.release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert control.target_epoch == target + 1 and control.state == "human"
    assert (
        len(
            [
                method
                for method, _ in page.calls
                if method
                in ("Page.navigate", "Page.reload", "Page.navigateToHistoryEntry")
            ]
        )
        == 1
    )
    with pytest.raises(ControlError, match="^stale_browser_operation$"):
        await control.run("original-human", epoch, target, current)


async def test_withdrawal_during_history_read_keeps_navigation_unsent():
    allowed = True

    async def grant():
        if not allowed:
            raise PermissionError("withdrawn original principal")

    class Withdrawn(Page):
        async def call(self, method, params=None):
            nonlocal allowed
            result = await super().call(method, params)
            if method == "Page.getNavigationHistory":
                allowed = False
            return result

    page = Withdrawn()
    session, control = await session_for(page)
    target = control.target_epoch
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await session.action(
            "original-human",
            control.epoch,
            target,
            {"kind": "back"},
            before_effect=grant,
        )
    assert control.target_epoch == target
    assert [method for method, _ in page.calls] == ["Page.getNavigationHistory"]


@pytest.mark.parametrize(
    "method", ["Page.navigate", "Page.reload", "Page.navigateToHistoryEntry"]
)
async def test_agent_navigation_uses_same_version_boundary_and_keeps_protocol_result(
    method,
):
    page = Page()
    session, control = await session_for(page)
    # The same selected page is explicitly returned to AI ownership.
    await control.give_back("original-human", current)
    result = await session.agent_command(
        control.epoch,
        control.target_epoch,
        method,
        {"url": "https://fixture.invalid/next", "entryId": 1},
        before_effect=current,
    )
    assert result == {"frameId": "original-frame"}
    assert control.target_epoch == 1
    assert (
        len(
            [
                name
                for name, _ in page.calls
                if name
                in ("Page.navigate", "Page.reload", "Page.navigateToHistoryEntry")
            ]
        )
        == 1
    )


async def test_withdrawal_after_navigation_withholds_ack_but_keeps_new_version():
    allowed = True

    async def grant():
        if not allowed:
            raise PermissionError("withdrawn after original send")

    class Withdrawn(Page):
        async def call(self, method, params=None):
            nonlocal allowed
            result = await super().call(method, params)
            if method != "Page.getFrameTree":
                allowed = False
            return result

    page = Withdrawn()
    session, control = await session_for(page)
    target = control.target_epoch
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await session.action(
            "original-human",
            control.epoch,
            target,
            {"kind": "reload"},
            before_effect=grant,
        )
    assert control.target_epoch == target + 1
    assert [method for method, _ in page.calls] == ["Page.getFrameTree", "Page.reload"]
