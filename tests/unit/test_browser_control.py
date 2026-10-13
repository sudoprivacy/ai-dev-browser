"""Control-transfer races must not replay stale browser actions."""

import asyncio

import pytest

from ai_dev_browser.remote.control import BrowserControl, ControlError, SharedViewer


async def test_takeover_drains_and_discards_queued_ai_and_child_operations():
    control = BrowserControl()
    entered, release = asyncio.Event(), asyncio.Event()
    effects = []

    async def active():
        entered.set()
        await release.wait()
        effects.append("active-finished")

    async def stale():
        effects.append("must-not-run")

    active_task = asyncio.create_task(control.run("ai", 0, 0, active))
    await entered.wait()
    child_task = asyncio.create_task(control.run("ai", 0, 0, stale))
    await asyncio.sleep(0)
    transfer = asyncio.create_task(control.take("user-device"))
    await asyncio.sleep(0)
    assert control.state == "pausing"
    assert not transfer.done()
    with pytest.raises(ControlError, match="browser_control_not_owned"):
        await control.run("user-device", 1, 0, stale)
    release.set()
    await active_task
    with pytest.raises(ControlError, match="stale_browser_operation"):
        await child_task
    assert (await transfer)["state"] == "human"
    assert effects == ["active-finished"]
    with pytest.raises(ControlError, match="browser_control_held_by_user"):
        await control.run("ai", 1, 0, stale)
    with pytest.raises(ControlError, match="browser_control_not_owned"):
        await control.run("another-user", 1, 0, stale)


async def test_failed_or_cancelled_observation_keeps_human_control():
    control = BrowserControl()
    await control.take("user")

    async def failed():
        raise RuntimeError("browser disconnected")

    with pytest.raises(RuntimeError, match="disconnected"):
        await control.give_back("user", failed)
    assert control.state == "human"
    assert control.controller == "user"
    assert control.error == "browser_observation_required"
    entered = asyncio.Event()

    async def wait():
        entered.set()
        await asyncio.Event().wait()

    transfer = asyncio.create_task(control.give_back("user", wait))
    await entered.wait()
    transfer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await transfer
    assert control.state == "human"

    async def observe():
        return {"url": "current", "image": "fresh"}

    state, observation = await control.give_back("user", observe)
    assert state["state"] == "ai" and state["controller"] is None
    assert observation == {"url": "current", "image": "fresh"}


async def test_cancelled_agent_cannot_abandon_an_input_sequence():
    control = BrowserControl()
    pressed, release = asyncio.Event(), asyncio.Event()
    effects = []

    async def click():
        effects.append("pressed")
        pressed.set()
        await release.wait()
        effects.append("released")

    operation = asyncio.create_task(control.run("ai", 0, 0, click))
    await pressed.wait()
    operation.cancel()
    transfer = asyncio.create_task(control.take("user"))
    await asyncio.sleep(0)
    operation.cancel()
    await asyncio.sleep(0)
    assert control.state == "pausing" and not transfer.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert (await transfer)["state"] == "human"
    assert effects == ["pressed", "released"]


async def test_interrupted_takeover_stays_stopped_and_can_be_recovered():
    control = BrowserControl()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def active():
        entered.set()
        await release.wait()

    operation = asyncio.create_task(control.run("ai", 0, 0, active))
    await entered.wait()
    transfer = asyncio.create_task(control.take("user"))
    await asyncio.sleep(0)
    transfer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await transfer
    assert control.state == "error"
    with pytest.raises(ControlError, match="browser_control_not_owned"):
        await control.take("other-device")
    release.set()
    await operation
    assert (await control.take("user"))["state"] == "human"


async def test_target_change_invalidates_a_queued_click():
    control = BrowserControl()
    entered = asyncio.Event()
    release = asyncio.Event()
    effects = []

    async def navigate():
        entered.set()
        await release.wait()
        control.change_target()

    async def click():
        effects.append("wrong-tab")

    navigation = asyncio.create_task(control.run("ai", 0, 0, navigate))
    await entered.wait()
    queued = asyncio.create_task(control.run("ai", 0, 0, click))
    await asyncio.sleep(0)
    release.set()
    await navigation
    with pytest.raises(ControlError, match="stale_browser_operation"):
        await queued
    assert not effects


async def test_two_viewers_share_one_lazy_adapter_and_preserve_browser():
    created, closed = [], []

    async def create():
        created.append(object())
        return created[-1]

    async def close(view):
        closed.append(view)

    view = SharedViewer(create, close)
    assert not created
    panel, tab = await asyncio.gather(view.attach("panel"), view.attach("tab"))
    assert panel is tab and len(created) == 1
    await view.attach("panel")
    await view.detach("panel")
    assert not closed
    await view.detach("unknown")
    assert not closed
    await view.detach("tab")
    assert closed == [panel]
    await view.attach("reconnect")
    assert len(created) == 2
    await view.detach("reconnect")
