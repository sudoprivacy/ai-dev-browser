"""Regression: browser_start startup_timeout parameter + orphan cleanup.

Reported by sudowork/lis8 trace: on a Windows machine with the user's
main Chrome already running, fresh-profile cold start sometimes takes
>10s (Defender scan + I/O contention + first-time profile init). The
old hardcoded 10s timeout failed, but Chrome was actually starting
successfully — Python just gave up. Worse, the spawned Chrome was
never killed, so it kept holding the profile's lockfile and the next
browser_start with the same profile cascaded into "profile in use"
errors.

Fix verified here:
  - `startup_timeout` is a real parameter, default 30s, honored end-to-end
  - On timeout, the spawned Chrome process tree is killed so the
    profile lockfile is released and the caller can retry cleanly
"""

import os
import platform
import subprocess
import time

import pytest

from ai_dev_browser.core.browser import browser_start, browser_stop


SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


def _pid_alive(pid: int) -> bool:
    """Cross-platform PID-existence check. Used to verify the orphan was killed."""
    if platform.system() == "Windows":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
        )
        # tasklist returns header-only when no match; PID echoed when match
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def test_startup_timeout_param_accepted_and_honored():
    """Sanity: the parameter exists, accepts a float, and a normal-sized
    timeout still allows Chrome to come up successfully."""
    result = browser_start(headless=True, temp=True, startup_timeout=30.0)
    assert "error" not in result, f"normal startup with 30s should succeed: {result}"
    try:
        assert "port" in result
    finally:
        browser_stop(port=result["port"])


def test_startup_timeout_kills_orphan_chrome_on_timeout():
    """The headline regression: when timeout fires, the spawned Chrome
    process must be killed so it doesn't sit holding the profile lockfile.

    We force the timeout with `startup_timeout=0.001` (Chrome can't possibly
    bind in 1ms). browser_start should:
      1. Return an error dict
      2. Include the PID of the (now-killed) Chrome
      3. Mention the kill in the message so the caller knows to retry
    Then we verify the PID is genuinely no longer running.
    """
    result = browser_start(headless=True, temp=True, startup_timeout=0.001)
    assert "error" in result, f"tight timeout should fail, got {result}"
    assert "killed" in result["error"].lower(), (
        f"error should mention kill so caller knows to retry: {result['error']!r}"
    )
    pid = result.get("pid")
    assert pid is not None

    # The kill is best-effort. Give Chrome a beat to actually die — process
    # tree teardown isn't instant on Windows (taskkill /T fans out).
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not _pid_alive(pid):
            break
        time.sleep(0.2)

    assert not _pid_alive(pid), (
        f"Orphan Chrome PID {pid} still alive 5s after timeout — "
        "_kill_process_tree didn't take effect, profile lockfile will "
        "block subsequent browser_start calls (the original bug)."
    )
