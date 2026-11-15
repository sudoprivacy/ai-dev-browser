"""Host assertions belong inside transfer and view-allocation barriers."""

import asyncio

import pytest

from ai_dev_browser.remote.control import BrowserControl, ControlError, SharedViewer


class CurrentAccess:
    def __init__(self):
        self.allowed = True
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        if not self.allowed:
            raise PermissionError("private original grant")


async def test_take_rechecks_after_draining_sent_input():
    control, access = BrowserControl(), CurrentAccess()
    entered, release = asyncio.Event(), asyncio.Event()
    effects = []

    async def active():
        entered.set()
        await release.wait()
        effects.append("one completed input")

    sent = asyncio.create_task(control.run("ai", 0, 0, active))
    await entered.wait()
    pending = asyncio.create_task(control.take("user", before_effect=access))
    await asyncio.sleep(0)
    access.allowed = False
    release.set()
    await sent
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await pending
    assert effects == ["one completed input"]
    assert control.state == "error"
    assert control.controller == "user"
    assert access.calls == 2
    assert (await control.take("user", before_effect=CurrentAccess()))[
        "state"
    ] == "human"


async def test_take_does_not_accept_a_state_changed_during_initial_check():
    control = BrowserControl()

    async def check():
        control.change_target()

    with pytest.raises(ControlError, match="^stale_browser_operation$"):
        await control.take("user", before_effect=check)
    assert control.state == "ai"
    assert control.controller is None


async def test_denied_idempotent_take_does_not_return_a_lease():
    control, access = BrowserControl(), CurrentAccess()
    await control.take("user")
    before = control.snapshot()
    access.allowed = False
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await control.take("user", before_effect=access)
    assert control.snapshot() == before


async def test_return_rechecks_after_held_observation_before_releasing_ai():
    control, access = BrowserControl(), CurrentAccess()
    await control.take("user")
    entered, release = asyncio.Event(), asyncio.Event()
    observations = []

    async def observe():
        entered.set()
        await release.wait()
        observations.append("fresh observation")
        return {"image": "private"}

    pending = asyncio.create_task(
        control.give_back("user", observe, before_effect=access)
    )
    await entered.wait()
    access.allowed = False
    release.set()
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await pending
    assert observations == ["fresh observation"]
    assert control.state == "human"
    assert control.controller == "user"


async def test_return_rechecks_queued_grant_before_observation():
    control, access = BrowserControl(), CurrentAccess()
    await control.take("user")
    await control._operations.acquire()
    observed = []

    async def observe():
        observed.append(True)

    pending = asyncio.create_task(
        control.give_back("user", observe, before_effect=access)
    )
    await asyncio.sleep(0)
    access.allowed = False
    control._operations.release()
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await pending
    assert not observed
    assert control.state == "human"


async def test_return_does_not_release_a_target_changed_during_observation():
    control = BrowserControl()
    await control.take("user")

    async def observe():
        control.change_target()
        return {"image": "old target"}

    with pytest.raises(ControlError, match="^browser_control_transfer_interrupted$"):
        await control.give_back("user", observe, before_effect=CurrentAccess())
    assert control.state == "human"
    assert control.controller == "user"


async def test_cancelled_return_check_preserves_true_cancellation():
    control = BrowserControl()
    await control.take("user")
    checking = asyncio.Event()
    observations = []

    async def check():
        checking.set()
        await asyncio.Event().wait()

    async def observe():
        observations.append(True)

    pending = asyncio.create_task(
        control.give_back("user", observe, before_effect=check)
    )
    await checking.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not observations
    assert control.state == "human"


async def test_revoked_view_allocation_closes_only_its_new_resource():
    access = CurrentAccess()
    created, closed = [], []

    async def create():
        created.append(object())
        access.allowed = False
        return created[-1]

    async def close(view):
        closed.append(view)

    viewer = SharedViewer(create, close)
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await viewer.attach("new", before_effect=access)
    assert closed == created
    assert viewer._owners == set()
    assert viewer._view is None


async def test_denied_queued_attach_preserves_existing_view_and_owner():
    access = CurrentAccess()
    created, closed = [], []

    async def create():
        created.append(object())
        return created[-1]

    async def close(view):
        closed.append(view)

    viewer = SharedViewer(create, close)
    original = await viewer.attach("panel")
    await viewer._lock.acquire()
    pending = asyncio.create_task(viewer.attach("window", before_effect=access))
    await asyncio.sleep(0)
    access.allowed = False
    viewer._lock.release()
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await pending
    assert viewer._view is original
    assert viewer._owners == {"panel"}
    assert len(created) == 1
    assert not closed
    await viewer.detach("panel")
    assert closed == [original]


async def test_view_cancelled_after_factory_return_closes_new_resource():
    checking = asyncio.Event()
    created, closed = [], []

    async def create():
        created.append(object())
        return created[-1]

    async def close(view):
        closed.append(view)

    async def check():
        if created:
            checking.set()
            await asyncio.Event().wait()

    viewer = SharedViewer(create, close)
    pending = asyncio.create_task(viewer.attach("new", before_effect=check))
    await checking.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert closed == created
    assert viewer._owners == set()
    assert viewer._view is None


@pytest.mark.parametrize("verdict", [True, False, {"allowed": True}])
async def test_malformed_transfer_authorization_does_not_change_lease(verdict):
    control = BrowserControl()
    original = control.snapshot()

    async def check():
        return verdict

    with pytest.raises(ControlError, match="^invalid_browser_authorization$"):
        await control.take("user", before_effect=check)
    assert control.snapshot() == original


async def test_failed_allocation_cleanup_is_retired_before_any_new_owner():
    access = CurrentAccess()
    created, closed = [], []

    async def create():
        created.append(object())
        if len(created) == 1:
            access.allowed = False
        return created[-1]

    async def close(view):
        closed.append(view)
        if len(closed) == 1:
            raise RuntimeError("owned adapter cleanup failed")

    viewer = SharedViewer(create, close)
    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await viewer.attach("old", before_effect=access)
    assert viewer._view is created[0]
    assert viewer._owners == set()
    assert viewer._retiring
    access.allowed = True
    fresh = await viewer.attach("new", before_effect=access)
    assert fresh is created[1]
    assert closed == [created[0], created[0]]
    assert viewer._owners == {"new"}
    assert not viewer._retiring
    await viewer.detach("new")
