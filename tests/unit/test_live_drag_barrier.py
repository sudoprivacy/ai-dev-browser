"""A live pointer remains one operation even when its HTTP caller disappears."""

import asyncio

import pytest

from ai_dev_browser.remote.control import BrowserControl, ControlError
from ai_dev_browser.remote.gesture import LiveDrag


class View:
    def __init__(self):
        self.events = []
        self.entered = asyncio.Event()
        self.block = None
        self.failure = None

    async def press(self, point):
        self.events.append(("press", point))

    async def move(self, point):
        self.entered.set()
        if self.block is not None:
            await self.block.wait()
        if self.failure:
            raise self.failure
        self.events.append(("move", point))

    async def release(self):
        self.events.append(("release", None))


async def owned_drag():
    control, view = BrowserControl(), View()
    await control.take("user-reviewer")
    drag = LiveDrag(
        control, "user-reviewer", control.epoch, 0, view, {"x": 20, "y": 20}
    )
    await drag.start()
    return control, view, drag


async def test_live_motion_precedes_release_and_queued_edits_remain_fenced():
    control, view, drag = await owned_drag()

    async def next_input():
        view.events.append(("next-input", None))

    queued = asyncio.create_task(
        control.run("user-reviewer", control.epoch, 0, next_input)
    )
    try:
        await drag.send("move", {"x": 25, "y": 25})
        assert not queued.done() and view.events[-1][0] == "move"
        assert all(kind != "release" for kind, _ in view.events)
        await drag.send("end", {"x": 30, "y": 30})
        await queued
        assert [kind for kind, _ in view.events] == [
            "press",
            "move",
            "move",
            "release",
            "next-input",
        ]
        assert control.state == "human" and control.controller == "user-reviewer"
    finally:
        await drag.close()
        await queued


async def test_failed_motion_propagates_after_balanced_release_without_replay():
    control, view, drag = await owned_drag()
    view.failure = RuntimeError("native input failed")
    with pytest.raises(RuntimeError, match="native input failed"):
        await drag.send("move", {"x": 25, "y": 25})
    await drag.close()
    assert [kind for kind, _ in view.events] == ["press", "release"]
    assert not control._operations.locked()
    assert control.state == "human" and control.controller == "user-reviewer"


async def test_explicit_return_invalidates_motion_and_observes_after_release():
    control, view, drag = await owned_drag()

    async def observe():
        assert view.events[-1][0] == "release"
        return "fresh page"

    returning = asyncio.create_task(control.give_back("user-reviewer", observe))
    await asyncio.sleep(0)
    assert control.state == "observing" and not returning.done()
    with pytest.raises(ControlError, match="stale_browser_operation"):
        await drag.send("move", {"x": 25, "y": 25})
    snapshot, observed = await returning
    assert snapshot["state"] == "ai" and observed == "fresh page"
    assert [kind for kind, _ in view.events] == ["press", "release"]
    await drag.close()


async def test_cancelled_caller_does_not_abandon_inflight_input_or_grant_control():
    control, view, drag = await owned_drag()
    view.block = asyncio.Event()
    sending = asyncio.create_task(drag.send("move", {"x": 25, "y": 25}))
    await view.entered.wait()
    sending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await sending
    assert control._operations.locked()
    closing = asyncio.create_task(drag.close())
    view.block.set()
    await closing
    assert [kind for kind, _ in view.events] == ["press", "move", "release"]
    assert control.state == "human" and control.controller == "user-reviewer"


async def test_unowned_press_is_rejected_before_native_input():
    control, view = BrowserControl(), View()
    drag = LiveDrag(control, "user-other", 0, 0, view, {"x": 20, "y": 20})
    with pytest.raises(ControlError, match="browser_control_not_owned"):
        await drag.start()
    assert view.events == [] and control.state == "ai"
    await drag.close()


async def test_uncertain_release_fences_queued_coordinates_and_retains_owner():
    control, view, drag = await owned_drag()

    async def uncertain_release():
        raise RuntimeError("native release failed")

    view.release = uncertain_release
    epoch = control.epoch
    with pytest.raises(RuntimeError, match="native release failed"):
        await drag.send("end", {"x": 25, "y": 25})
    assert control.state == "error" and control.controller == "user-reviewer"
    assert control.error == "browser_drag_release_uncertain" and control.epoch > epoch
    with pytest.raises(ControlError, match="stale_browser_operation"):
        await control.run("user-reviewer", epoch, 0, uncertain_release)
    await drag.close()


async def test_cancel_fences_queued_input_without_returning_control():
    control, view, drag = await owned_drag()
    epoch = control.epoch

    async def stale_input():
        pytest.fail("Cancelled gesture released stale queued coordinates")

    queued = asyncio.create_task(control.run("user-reviewer", epoch, 0, stale_input))
    await drag.send("cancel", None)
    with pytest.raises(ControlError, match="stale_browser_operation"):
        await queued
    assert control.epoch > epoch and control.state == "human"
    assert control.controller == "user-reviewer"
    assert [kind for kind, _ in view.events] == ["press", "release"]
    await drag.close()


async def test_explicit_return_cannot_override_uncertain_native_release():
    control, view, drag = await owned_drag()

    async def uncertain_release():
        raise RuntimeError("native release failed")

    async def observe():
        pytest.fail("An uncertain native release was accepted as safe")

    view.release = uncertain_release
    returning = asyncio.create_task(control.give_back("user-reviewer", observe))
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="native release failed"):
        await drag.send("move", {"x": 25, "y": 25})
    with pytest.raises(ControlError, match="browser_control_transfer_interrupted"):
        await returning
    assert control.state == "error" and control.controller == "user-reviewer"
    assert control.error == "browser_drag_release_uncertain"
    await drag.close()


async def test_disconnect_rejects_new_motion_and_concurrent_closes_release_once():
    control, view, drag = await owned_drag()
    view.block = asyncio.Event()
    moving = asyncio.create_task(drag.send("move", {"x": 25, "y": 25}))
    await view.entered.wait()
    first_close = asyncio.create_task(drag.close())
    await asyncio.sleep(0)
    with pytest.raises(ControlError, match="browser_drag_closed"):
        await drag.send("move", {"x": 28, "y": 28})
    second_close = asyncio.create_task(drag.close())
    view.block.set()
    await asyncio.gather(moving, first_close, second_close)
    assert [kind for kind, _ in view.events] == ["press", "move", "release"]
    assert control.state == "human" and control.controller == "user-reviewer"
