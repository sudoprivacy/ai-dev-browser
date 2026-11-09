"""Unsent-operation guarantees for host checks inside the public barrier."""

import asyncio

import pytest

from ai_dev_browser.remote.control import BrowserControl, ControlError


@pytest.mark.parametrize("verdict", [False, True, {"allowed": False}])
async def test_malformed_host_completion_never_submits(verdict):
    control = BrowserControl()
    effects = []

    async def check():
        return verdict

    async def input():
        effects.append("sent")

    with pytest.raises(ControlError, match="^invalid_browser_authorization$"):
        await control.run("ai", 0, 0, input, before_effect=check)
    assert effects == []


async def test_cancelled_host_check_releases_unsent_barrier_without_input():
    control = BrowserControl()
    checking = asyncio.Event()
    effects = []

    async def check():
        checking.set()
        await asyncio.Event().wait()

    async def input():
        effects.append("sent")

    pending = asyncio.create_task(control.run("ai", 0, 0, input, before_effect=check))
    await checking.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert effects == []
    # Cancellation occurred before submission, so an unrelated valid input can
    # still acquire this same barrier. Sent-input cancellation is tested apart.
    await control.run("ai", 0, 0, input)
    assert effects == ["sent"]


async def test_private_host_error_is_not_exposed():
    control = BrowserControl()

    async def check():
        raise PermissionError("private credential and original endpoint")

    async def input():
        raise AssertionError("input must remain unsent")

    with pytest.raises(ControlError, match="^browser_authorization_denied$"):
        await control.run("ai", 0, 0, input, before_effect=check)
