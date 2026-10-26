"""Status must not query a driver while its owned browser is being retired."""

import asyncio
from types import SimpleNamespace

import pytest

from ai_dev_browser.core._transport import ProtocolException
from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.worker import Worker


async def test_first_host_start_drains_ai_before_acknowledging_human_control(tmp_path):
    worker = Worker(tmp_path, "host", "agent", display_mode="native")
    entered, release = asyncio.Event(), asyncio.Event()
    launches = []

    async def in_flight():
        entered.set()
        await release.wait()

    async def start_browser(action, actor):
        assert worker.control.state == "human"
        assert worker.control.controller == actor == "user-controller"
        launches.append(action)

    worker._start_browser = start_browser
    operation = asyncio.create_task(worker.control.run("ai", 0, 0, in_flight))
    await entered.wait()
    starting = asyncio.create_task(
        worker.start({"isHeadless": True, "transport": "cdp"}, "user-controller")
    )
    await asyncio.sleep(0)
    assert worker.control.state == "pausing" and not launches
    release.set()
    await operation
    await starting
    assert len(launches) == 1 and worker.control.state == "human"


async def test_invalid_host_start_does_not_change_the_control_lease(tmp_path):
    worker = Worker(tmp_path, "host", "agent", display_mode="native")
    before = worker.control.snapshot()
    with pytest.raises(ControlError, match="explicit_browser_launch_mode_required"):
        await worker.start({"transport": "cdp"}, "user-controller")
    assert worker.control.snapshot() == before


async def test_concurrent_status_readers_preserve_idle_human_control(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    worker = Worker(tmp_path, "host", "agent", display_mode="native")
    worker.bind({"orgId": "org", "userId": "user", "sessionId": "conversation"})
    worker.control.controller = "user-controller"
    worker.control.state = "human"
    worker.browser = {
        "session_id": "same-browser",
        "headless": True,
        "transport": "cdp",
    }

    class ReadingSession:
        async def state(self):
            entered.set()
            await release.wait()
            return {
                **worker.control.snapshot(),
                "activeTargetId": "same-tab",
                "tabs": [{"id": "same-tab", "title": "Review", "url": "about:blank"}],
            }

    worker.session = ReadingSession()
    first = asyncio.create_task(worker.state("user-controller"))
    await entered.wait()
    second = asyncio.create_task(worker.state("user-controller"))
    await asyncio.sleep(0)
    release.set()
    snapshots = await asyncio.gather(first, second)
    assert all(value["state"] == "human" for value in snapshots)
    assert all(
        value["isController"] and value["isHumanControlHeld"] for value in snapshots
    )
    assert all(value["capabilities"]["pageView"] for value in snapshots)
    assert all(value["activeTargetId"] == "same-tab" for value in snapshots)


@pytest.mark.parametrize("is_stop_confirmed", [True, False])
async def test_status_preserves_the_human_lease_during_browser_close(
    tmp_path, monkeypatch, is_stop_confirmed
):
    entered, release = asyncio.Event(), asyncio.Event()
    worker = Worker(tmp_path, "host", "agent", display_mode="native")
    worker.bind({"orgId": "org", "userId": "user", "sessionId": "conversation"})
    worker.control.controller = "user-controller"
    worker.control.state = "human"
    worker.browser = {
        "session_id": "retiring-browser",
        "headless": False,
        "transport": "extension",
    }

    async def close_browser():
        pass

    class RetiringSession:
        browser = SimpleNamespace(close=close_browser)

        async def close(self):
            entered.set()
            await release.wait()

        async def state(self):
            # This is the actual protocol failure returned by the production
            # extension after close has started. Status must not touch it.
            raise ProtocolException(
                "Browser session changed; reconnect explicitly and inspect state before further input"
            )

    worker.session = RetiringSession()
    stop_calls = []

    def stop(*, session_id):
        stop_calls.append(session_id)
        return {"stopped": is_stop_confirmed}

    monkeypatch.setattr("ai_dev_browser.remote.worker.browser_stop", stop)
    task = asyncio.create_task(
        worker.invoke(
            "user-controller", {"kind": "stop", "controlEpoch": 0, "targetEpoch": 0}
        )
    )
    try:
        await entered.wait()
        current = (await worker.invoke("user-controller", {"kind": "state"}))["session"]
        assert current["state"] == "pausing"
        assert current["isController"] and current["isHumanControlHeld"]
        assert not current["capabilities"]["pageView"]
        assert not current["capabilities"]["windowView"]
        assert current["activeTargetId"] is None and current["tabs"] == []
    finally:
        release.set()
        if is_stop_confirmed:
            stopped = (await task)["session"]
            assert stopped["state"] == "stopped" and stopped["isHumanControlHeld"]
        else:
            with pytest.raises(ControlError, match="browser_stop_uncertain"):
                await task
            stopped = (await worker.invoke("user-controller", {"kind": "state"}))[
                "session"
            ]
            assert stopped["error"] == "browser_restart_requires_observation"
            assert stopped["isHumanControlHeld"]
    assert stop_calls == ["retiring-browser"]
