"""Regression: get_pid_on_port survives non-UTF-8 system locale.

Reported on Windows with Chinese (GBK) system locale: the netstat -ano
output contained bytes that GBK can't decode, so subprocess.run's
text=True decode raised UnicodeDecodeError, result.stdout came back as
None, and the next line's `.split("\\n")` crashed with AttributeError.
Net effect — connect_browser() / get_active_tab() auto port discovery
silently broke, forcing every caller to pass --port manually.

The fix pins `encoding="utf-8", errors="ignore"` and guards
`result.stdout` with `(result.stdout or "")` so neither decoding nor a
None stdout can take down auto-discovery.

These tests don't reproduce the GBK decode path on a UTF-8 CI host —
they verify the public contract end-to-end on whatever locale the CI
machine has. On the bug reporter's Chinese-Windows CI, removing
`errors="ignore"` or the None-guard puts these back into the
AttributeError state and the suite fails loudly. On UTF-8 CI they
defend against any future regression that breaks the happy path.
"""

import os
import socket

import pytest

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser
from ai_dev_browser.core.process import get_pid_on_port


SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


def _find_free_port() -> int:
    """Ask the OS for an ephemeral port nothing is listening on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_get_pid_on_port_returns_pid_for_real_listener():
    """Headline regression: launching Chrome and asking which PID owns
    its debug port must round-trip cleanly. Pre-fix, this crashed with
    AttributeError on Chinese-Windows because the netstat decode wiped
    result.stdout."""
    result = browser_start(headless=True, temp=True)
    assert "error" not in result, f"browser_start should succeed: {result}"
    port = result["port"]
    expected_pid = result["pid"]

    try:
        # The function under test. Pre-fix: AttributeError on GBK
        # locale because subprocess result.stdout was None.
        pid = get_pid_on_port(port)
        assert pid is not None, (
            f"get_pid_on_port({port}) returned None even though Chrome "
            f"PID {expected_pid} is listening there — auto-discovery is "
            "broken (the original Chinese-Windows symptom)."
        )
        assert isinstance(pid, int), (
            f"get_pid_on_port({port}) returned {pid!r} of type "
            f"{type(pid).__name__}; expected int."
        )
    finally:
        browser_stop(port=port)


def test_get_pid_on_port_returns_none_for_unused_port_without_crash():
    """Defense in depth: the None-path itself must not raise. Pre-fix,
    even the unused-port path could crash if `result.stdout` came back
    as None — the `.split("\\n")` was unguarded."""
    free_port = _find_free_port()
    # No try/except — the contract is "return None, never raise".
    pid = get_pid_on_port(free_port)
    assert pid is None, (
        f"get_pid_on_port({free_port}) returned {pid!r} for an unused "
        "port; expected None."
    )


def test_connect_browser_zero_arg_auto_discovery_works_end_to_end(
    tmp_path, monkeypatch
):
    """Integration: the bug's user-visible symptom was that
    `connect_browser()` zero-arg auto-detection broke and callers had
    to pass --port on every call. This exercises the full chain
    browser_start → get_pid_on_port → connect_browser() and asserts the
    no-arg form actually finds the freshly-launched Chrome.

    Pre-fix on Chinese Windows: connect_browser() raised. Post-fix:
    returns a usable BrowserClient connected to the right port.

    Runs from its own cwd. Zero-arg discovery scans the Chromes of the *current
    workspace*, and a workspace is just a slug of the cwd — so run from the repo
    root, this test could see any other Chrome anyone had started from the repo
    root (another test's leftover, a developer's scratch browser) and assert
    against it. That made it pass or fail depending on what else happened to be
    running, which is the definition of a flaky test. A private cwd is a private
    workspace, so the Chrome started below is provably the only candidate.
    """
    import asyncio

    monkeypatch.chdir(tmp_path)

    start = browser_start(headless=True, temp=True)
    assert "error" not in start, f"browser_start should succeed: {start}"
    port = start["port"]

    try:

        async def _attach():
            browser = await connect_browser()
            try:
                # Connecting via auto-detect should have landed on the
                # same Chrome we just started.
                assert browser.port == port, (
                    f"connect_browser() auto-detected port {browser.port} "
                    f"but the only Chrome in this workspace is on {port} — "
                    "discovery picked the wrong process or no process."
                )
            finally:
                await browser.close()

        asyncio.run(_attach())
    finally:
        browser_stop(port=port)
