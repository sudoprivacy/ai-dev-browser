"""Per-packet current assertions cannot strand a pressed pointer."""

import asyncio

import pytest

from ai_dev_browser.remote.control import BrowserControl, ControlError
from ai_dev_browser.remote.gesture import LiveDrag


class View:
    def __init__(self):
        self.events = []

    async def press(self, point):
        self.events.append(("press", point))

    async def move(self, point):
        self.events.append(("move", point))

    async def release(self):
        self.events.append(("release", None))


async def owned_drag():
    control, view = BrowserControl(), View()
    await control.take("user")
    return control, view, LiveDrag(control, "user", 1, 0, view, {"x": 0, "y": 0})


async def test_denied_initial_drag_never_presses():
    control, view, drag = await owned_drag()

    async def denied():
        raise PermissionError("private original grant")

    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await drag.start(before_effect=denied)
    await drag.close()
    assert view.events == []
    assert control.state == "human"
    assert not control._operations.locked()


async def test_cancelled_unsent_drag_check_retires_driver_without_press():
    control, view, drag = await owned_drag()
    checking = asyncio.Event()

    async def checking_grant():
        checking.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(drag.start(before_effect=checking_grant))
    await checking.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await drag.close()
    assert drag.task.done() and drag.task.cancelled()
    assert view.events == []
    assert control.state == "human"
    assert not control._operations.locked()


async def test_held_packet_revoke_releases_once_without_endpoint_or_replay():
    control, view, drag = await owned_drag()
    entered, release = asyncio.Event(), asyncio.Event()
    allowed = True
    await drag.start()

    async def check():
        entered.set()
        await release.wait()
        if not allowed:
            raise PermissionError("private original grant")

    pending = asyncio.create_task(
        drag.send("move", {"x": 10, "y": 10}, before_effect=check)
    )
    await entered.wait()
    allowed = False
    release.set()
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await pending
    await drag.close()
    assert [kind for kind, _ in view.events] == ["press", "release"]
    assert control.state == "human" and control.controller == "user"
    assert control.epoch == 2
    assert not control._operations.locked()


async def test_withdrawal_between_coalesced_moves_keeps_balanced_release():
    control, view, drag = await owned_drag()
    allowed = True
    original = view.move

    async def move(point):
        nonlocal allowed
        await original(point)
        allowed = False

    async def check():
        if not allowed:
            raise PermissionError("private original grant")

    view.move = move
    await drag.start()
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await drag.send("end", {"x": 100, "y": 100}, before_effect=check)
    await drag.close()
    assert view.events == [
        ("press", {"x": 0, "y": 0}),
        ("move", {"x": 50, "y": 50}),
        ("release", None),
    ]
    assert control.state == "human"
    assert control.epoch == 2


async def test_malformed_initial_drag_assertion_is_not_consent():
    control, view, drag = await owned_drag()

    async def malformed():
        return True

    with pytest.raises(ControlError, match="^invalid_browser_authorization$"):
        await drag.start(before_effect=malformed)
    await drag.close()
    assert not view.events
    assert control.state == "human"
