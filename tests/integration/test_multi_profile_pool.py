"""Regressions from a parallel worker-pool report (grok-downloaded-video-
local-organizer via grok-web-connector v0.7.0).

Bug A: `browser_start(reuse="any", profile="wN")` called 3 times with 3
  distinct profile names used to return the same Chrome for all calls —
  the default reuse path was profile-agnostic. Any pool using distinct
  profiles for isolation was silently collapsing onto one Chrome.

Bug B: `browser_stop` called from inside a running asyncio event loop
  emitted `RuntimeWarning: coroutine 'graceful_close_browser' was never
  awaited`. `asyncio.run(graceful_close_browser(port=port))` eagerly
  built the coroutine before asyncio.run rejected it, so the orphan
  never got awaited or explicitly closed.
"""

import asyncio
import os
import time
import warnings

import pytest

from ai_dev_browser.core.browser import (
    _graceful_stop,
    browser_start,
    browser_stop,
)
from ai_dev_browser.core.port import get_pid_on_port


SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


# -----------------------------------------------------------------------------
# Bug A: reuse must honor profile
# -----------------------------------------------------------------------------


def _unique_profile(suffix: str) -> str:
    """Per-test-run unique profile name so leftover Chrome profile locks
    from a previous failed test don't collide with this one."""
    return f"test-pool-{suffix}-{os.getpid()}-{int(time.time() * 1000) % 100000}"


def test_parallel_profiles_do_not_collapse_to_one_chrome():
    """Three browser_start calls with three distinct profiles must yield
    three distinct Chromes — the exact scenario a worker pool relies on
    for per-profile state isolation.
    """
    profiles = [_unique_profile(f"para{i}") for i in range(3)]
    results = []
    try:
        for i, profile in enumerate(profiles):
            r = browser_start(headless=True, profile=profile, reuse="any")
            assert "error" not in r, f"worker {i} failed to start: {r}"
            results.append(r)

        ports = [r["port"] for r in results]
        assert len(set(ports)) == 3, (
            f"Expected 3 distinct Chromes for 3 distinct profiles, "
            f"got ports={ports}. profile-aware reuse regressed."
        )

        # None of them should be marked "reused" — each needed its own profile
        reused_flags = [r.get("reused") for r in results]
        assert reused_flags == [False, False, False], (
            f"No existing profile-matching Chrome for any call, but got "
            f"reused={reused_flags}"
        )
    finally:
        for r in results:
            port = r.get("port")
            if port:
                browser_stop(port=port)


def test_same_profile_reuses_existing_chrome():
    """Counterpart of the above: calling browser_start twice with the SAME
    profile should reuse the existing Chrome (previous behaviour, must not
    regress)."""
    profile = _unique_profile("same")
    first = browser_start(headless=True, profile=profile)
    try:
        assert "error" not in first
        assert first["reused"] is False
        first_port = first["port"]

        second = browser_start(headless=True, profile=profile)
        assert "error" not in second
        assert second["reused"] is True, (
            "Second call with matching profile should reuse first Chrome"
        )
        assert second["port"] == first_port
    finally:
        browser_stop(port=first["port"])


def test_temp_never_reuses():
    """`temp=True` wants a throw-away profile — reusing any existing Chrome
    would silently tie the temp-flagged call to someone else's persistent
    state."""
    first = browser_start(headless=True, profile=_unique_profile("temp-iso"))
    try:
        assert first["reused"] is False
        temp = browser_start(headless=True, temp=True)
        try:
            assert temp["reused"] is False, (
                f"temp=True must not reuse another Chrome: {temp}"
            )
            assert temp["port"] != first["port"]
        finally:
            browser_stop(port=temp["port"])
    finally:
        browser_stop(port=first["port"])


# -----------------------------------------------------------------------------
# Bug B: no orphan coroutine when _graceful_stop runs inside an event loop
# -----------------------------------------------------------------------------


async def test_graceful_stop_inside_event_loop_emits_no_runtime_warning():
    """Call the in-loop branch of _graceful_stop and assert no
    RuntimeWarning leaks out. Previously asyncio.run built the coroutine
    eagerly; when asyncio.run rejected it, the coroutine was never awaited.
    """
    result = browser_start(headless=True, temp=True)
    assert "error" not in result
    port = result["port"]
    pid = get_pid_on_port(port)
    assert pid is not None

    # We ARE inside an event loop here (async test).
    # Any RuntimeWarning about un-awaited coroutines should surface.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # Run the blocking helper in a default executor so it doesn't
        # itself try to asyncio.run on top of the live loop.
        loop = asyncio.get_running_loop()
        stop_result = await loop.run_in_executor(None, _graceful_stop, port, pid)

    orphans = [
        w
        for w in caught
        if issubclass(w.category, RuntimeWarning)
        and "never awaited" in str(w.message)
        and "graceful_close_browser" in str(w.message)
    ]
    assert not orphans, (
        f"_graceful_stop leaked un-awaited coroutine: "
        f"{[str(w.message) for w in orphans]}"
    )
    assert stop_result["method"] in ("graceful", "force")
