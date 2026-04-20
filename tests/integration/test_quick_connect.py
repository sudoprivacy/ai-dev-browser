"""quick_connect — one-line ad-hoc Python script setup.

Reported by sudowork lis8 trace: LLMs writing combined-CLI scripts via
shell tool (`python -c "..."`) wasted 4 steps figuring out the
import + browser_start + connect_browser + get_active_tab boilerplate.
quick_connect collapses that to one async-context-manager call,
auto-detecting a running browser or starting one.

Resolution order tested here:
  1. Explicit port — attaches to that one
  2. AI_DEV_BROWSER_PORT env var
  3. workspace scan (find_workspace_chromes)
  4. start_if_needed=True falls through to browser_start
  5. start_if_needed=False raises when nothing found
"""

import os

import pytest

from ai_dev_browser import quick_connect
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


async def test_quick_connect_starts_browser_when_none_running(monkeypatch):
    """End-to-end smoke: no env, no existing browser → quick_connect
    starts one, yields a working Tab, exit closes CDP but leaves Chrome.
    """
    # Make sure auto-detect can't find anything pre-existing
    monkeypatch.delenv("AI_DEV_BROWSER_PORT", raising=False)

    # Track the port that gets started so we can clean up after
    started_port: int | None = None

    async with quick_connect(headless=True, temp=True) as tab:
        # The Tab must actually be usable
        title = await tab.evaluate("document.title")
        assert isinstance(title, str)
        # Capture the port the underlying Chrome bound — used for teardown
        started_port = tab._connection.websocket_url.split(":")[2].split("/")[0]
        started_port = int(started_port)

    # Chrome should still be alive after exit (quick_connect only releases
    # the CDP connection, doesn't browser_stop)
    try:
        from ai_dev_browser.core.port import is_port_in_use

        assert is_port_in_use(port=started_port), (
            "quick_connect should leave Chrome alive on exit so the next "
            "script can attach again"
        )
    finally:
        browser_stop(port=started_port)


async def test_quick_connect_attaches_to_existing_via_port_arg():
    """Explicit port arg — quick_connect attaches to a Chrome the caller
    already started, doesn't spawn a new one."""
    pre = browser_start(headless=True, temp=True)
    assert "error" not in pre
    port = pre["port"]
    try:
        async with quick_connect(port=port) as tab:
            value = await tab.evaluate("1 + 1", return_by_value=True)
            assert value == 2
    finally:
        browser_stop(port=port)


async def test_quick_connect_attaches_to_existing_via_env_var(monkeypatch):
    """AI_DEV_BROWSER_PORT env var — common orchestrator-injected pattern."""
    pre = browser_start(headless=True, temp=True)
    assert "error" not in pre
    port = pre["port"]
    try:
        monkeypatch.setenv("AI_DEV_BROWSER_PORT", str(port))
        async with quick_connect() as tab:
            value = await tab.evaluate("'hello'", return_by_value=True)
            assert value == "hello"
    finally:
        browser_stop(port=port)


async def test_quick_connect_raises_when_start_if_needed_false_and_nothing_found(
    monkeypatch,
):
    """Fail-loud mode: caller wants to attach to existing or fail —
    no surprise browser launch."""
    monkeypatch.delenv("AI_DEV_BROWSER_PORT", raising=False)
    # Stop any running browsers first so workspace scan finds nothing
    browser_stop(stop_all=True)

    with pytest.raises(RuntimeError, match="no running ai-dev-browser Chrome"):
        async with quick_connect(start_if_needed=False) as _tab:
            pass  # pragma: no cover (raises before yield)
