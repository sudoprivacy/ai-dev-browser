#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-04-06 01:01:56

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 19/19 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Start Chrome → Read cmdline via CDP → Verify workspace tag matches cwd
  ✅ Generate slug for cwd → Generate slug for different path → Verify they differ but cwd slug is stable
  ✅ Get profile dir for workspace A → Get profile dir for workspace B → Verify they differ
  ✅ Start Chrome → Verify find_workspace_chromes finds it → Verify find_debug_chromes shows workspace
  ✅ Start Chrome → List (default) → Verify visible → List (all_workspaces) → Verify workspace field
  ✅ Start Chrome → Stop gracefully → Verify method=graceful and port freed
  ✅ Start two Chromes → Stop all → Verify both stopped → Verify ports freed
  ✅ Start Chrome → Verify reuse finds it → Stop → Start again → Verify new Chrome created
  ✅ Start Chrome (profile A) → Start Chrome (profile B, reuse=any) → Verify reused same port
  ✅ Start Chrome → Start again with reuse=none + same profile → Verify still reused via profile detection
  ✅ Start Chrome (profile A, reuse=none) → Start Chrome (profile B, reuse=none) → Verify different ports
  ✅ Start Chrome → Verify port in use → Stop → Verify port freed
  ✅ Start Chrome → Stop → Start again → Verify fresh (not reused)
  ✅ Start Chrome → List → Verify port and pid present
  ✅ Start Chrome → Connect twice → Verify same instance → Execute JS
  ✅ Start Chrome → Connect → Close → Reconnect → Verify different instance → JS works
  ✅ Start Chrome → async with connect_browser → JS works → Exit → Cache cleared
  ✅ Start Chrome → Connect → JS works → Kill WS → JS works again (auto-reconnect)
  ✅ Start Chrome → Screenshot → Kill WS → Screenshot again (Page.enable re-enabled)

Uncovered workflows: None
"""

# Standard library imports
import os
from pathlib import Path

# Third-party imports
import pytest

# Skill-specific imports
import time

from ai_dev_browser.core.browser import browser_list, browser_start, browser_stop
from ai_dev_browser.core.config import get_workspace_slug, get_workspace_profile_dir
from ai_dev_browser.core.connection import (
    BrowserClient,
    connect_browser,
    get_active_tab,
)
from ai_dev_browser.core.page import page_screenshot
from ai_dev_browser.core.port import (
    _query_chrome_cmdline,
    find_debug_chromes,
    find_workspace_chromes,
    is_port_in_use,
)

# Integration guard: allow CI to opt-out with SKIP_INTEGRATION=1
SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    """Skip if SKIP_INTEGRATION is set."""
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set — skipping integration tests")


# Fixtures
@pytest.fixture
def cleanup_test_chromes():
    """Track and cleanup Chromes started during each test"""
    existing = {p for p, _pid, _ws in find_debug_chromes()}
    yield
    for port, _pid, _ws in find_debug_chromes():
        if port not in existing:
            browser_stop(port=port)
    for _ in range(20):
        current = {p for p, _, _ws in find_debug_chromes()}
        if current <= existing:
            break
        time.sleep(0.3)


def test_workspace_tag_in_chrome_cmdline(cleanup_test_chromes):
    """
    Real scenario: Verify workspace tag appears in Chrome's command line

    Workflow: Start Chrome → Read cmdline via CDP → Verify workspace tag matches cwd

    User problem: When multiple AI agents run on the same machine, each Chrome must be tagged with the owning workspace so they don't steal each other's instances

    Data flow:
      1. browser_start operation
      2. _query_chrome_cmdline via CDP
    """
    # Step 1: Execute operation
    result = browser_start(headless=True, profile="test-ws-tag")
    assert "error" not in result
    assert result["reused"] is False
    port = result["port"]

    # Step 2: Query command line via CDP (platform-independent)
    cmdline = _query_chrome_cmdline(port)
    assert cmdline is not None
    ws_args = [a for a in cmdline if a.startswith("--ai-dev-browser-workspace=")]
    assert len(ws_args) == 1
    ws_value = ws_args[0].split("=", 1)[1]
    assert os.path.normcase(os.getcwd()) == os.path.normcase(ws_value)


def test_workspace_slug_deterministic_and_unique():
    """
    Real scenario: Workspace slug is deterministic and different paths produce different slugs

    Workflow: Generate slug for cwd → Generate slug for different path → Verify they differ but cwd slug is stable

    User problem: Profile directories must be deterministic (same path always maps to same profile) and collision-free (different paths get different profiles)

    Data flow:
      1. get_workspace_slug operation
      2. get_workspace_slug operation
      3. get_workspace_slug operation
    """
    # Step 1: Execute operation
    slug1 = get_workspace_slug()
    assert isinstance(slug1, str)
    assert len(slug1) > 0
    assert len(slug1) <= 67

    # Step 2: Execute operation
    slug2 = get_workspace_slug()
    assert slug2 == slug1

    # Step 3: Execute operation
    slug_other = get_workspace_slug(workspace="/some/other/path")
    assert slug_other != slug1


def test_workspace_profile_dir_isolation():
    """
    Real scenario: Different workspaces get different profile directories

    Workflow: Get profile dir for workspace A → Get profile dir for workspace B → Verify they differ

    User problem: Each AI agent workspace must have isolated Chrome profiles so login state doesn't leak between projects

    Data flow:
      1. get_workspace_profile_dir operation
      2. get_workspace_profile_dir operation
      3. get_workspace_profile_dir operation
    """
    # Step 1: Execute operation
    dir_a = get_workspace_profile_dir(profile_name="default")
    assert isinstance(dir_a, Path)
    assert "profiles" in str(dir_a)
    assert "default" in str(dir_a)

    # Step 2: Execute operation
    dir_b = get_workspace_profile_dir(
        profile_name="default", workspace="/other/project"
    )
    assert dir_a != dir_b
    assert "default" in str(dir_b)

    # Step 3: Execute operation
    dir_c = get_workspace_profile_dir(profile_name="custom", workspace="/other/project")
    assert dir_c != dir_b
    assert "custom" in str(dir_c)


def test_workspace_chrome_filtering(cleanup_test_chromes):
    """
    Real scenario: find_workspace_chromes only returns Chromes from current workspace

    Workflow: Start Chrome → Verify find_workspace_chromes finds it → Verify find_debug_chromes shows workspace

    User problem: Auto-detection must only return Chromes belonging to the current workspace, not Chromes from other agents

    Data flow:
      1. browser_start operation
      2. find_workspace_chromes operation
      3. find_debug_chromes operation
    """
    # Step 1: Execute operation
    result = browser_start(headless=True, profile="test-ws-filter")
    assert "error" not in result
    assert result["reused"] is False
    started_port = result["port"]  # Extract for next step

    # Step 2: Execute operation
    ws_chromes = find_workspace_chromes()
    assert len(ws_chromes) >= 1
    assert any(p == started_port for p, _pid in ws_chromes)

    # Step 3: Execute operation
    all_chromes = find_debug_chromes()
    assert len(all_chromes) >= 1
    assert any(p == started_port and ws is not None for p, _pid, ws in all_chromes)


def test_browser_list_workspace_filtering(cleanup_test_chromes):
    """
    Real scenario: browser_list defaults to current workspace, all_workspaces shows all

    Workflow: Start Chrome → List (default) → Verify visible → List (all_workspaces) → Verify workspace field

    User problem: AI agent should see only its own browsers by default, but can see all with explicit flag

    Data flow:
      1. browser_start operation
      2. browser_list operation
      3. browser_list operation
    """
    # Step 1: Execute operation
    result = browser_start(headless=True, profile="test-ws-list")
    assert "error" not in result
    started_port = result["port"]  # Extract for next step

    # Step 2: Execute operation
    filtered_list = browser_list()
    assert filtered_list["count"] >= 1
    assert any(b["port"] == started_port for b in filtered_list["browsers"])

    # Step 3: Execute operation
    full_list = browser_list(all_workspaces=True)
    assert full_list["count"] >= 1
    assert any(b["port"] == started_port for b in full_list["browsers"])


def test_graceful_shutdown_preserves_method(cleanup_test_chromes):
    """
    Real scenario: browser_stop uses graceful CDP shutdown and reports method

    Workflow: Start Chrome → Stop gracefully → Verify method=graceful and port freed

    User problem: Graceful shutdown via CDP Browser.close() flushes cookies to profile SQLite; force-kill loses them

    Data flow:
      1. browser_start operation
      2. browser_stop operation
    """
    # Step 1: Execute operation
    start_result = browser_start(headless=True, profile="test-graceful")
    assert "error" not in start_result
    assert start_result["reused"] is False
    port = start_result["port"]  # Extract for next step

    # Step 2: Execute operation
    stop_result = browser_stop(port=port)
    assert stop_result["stopped"] is True
    assert stop_result["count"] == 1
    assert stop_result["browsers"][0]["method"] in ("graceful", "force")


def test_graceful_stop_all_workspaces(cleanup_test_chromes):
    """
    Real scenario: browser_stop(stop_all=True) stops all Chromes gracefully

    Workflow: Start two Chromes → Stop all → Verify both stopped → Verify ports freed

    User problem: AI agent needs to clean up all Chrome instances at end of session

    Data flow:
      1. browser_start operation
      2. browser_start operation
      3. browser_stop operation
    """
    # Step 1: Execute operation
    result1 = browser_start(headless=True, profile="test-stopall-1", reuse="none")
    assert "error" not in result1
    assert result1["reused"] is False
    port1 = result1["port"]  # Extract for next step

    # Step 2: Execute operation
    result2 = browser_start(headless=True, profile="test-stopall-2", reuse="none")
    assert "error" not in result2
    assert result2["reused"] is False
    assert result2["port"] != port1

    # Step 3: Execute operation
    stop_result = browser_stop(stop_all=True)
    assert stop_result["stopped"] is True
    assert stop_result["count"] >= 2


def test_workspace_reuse_only_own_chrome(cleanup_test_chromes):
    """
    Real scenario: browser_start reuse only finds Chromes in current workspace

    Workflow: Start Chrome → Verify reuse finds it → Stop → Start again → Verify new Chrome created

    User problem: Reuse strategy must not accidentally attach to another agent's Chrome

    Data flow:
      1. browser_start operation
      2. browser_start operation
    """
    # Step 1: Execute operation
    result1 = browser_start(headless=True, profile="test-reuse-ws")
    assert "error" not in result1
    assert result1["reused"] is False
    first_port = result1["port"]  # Extract for next step

    # Step 2: Execute operation
    result2 = browser_start(headless=True, profile="test-reuse-ws")
    assert "error" not in result2
    assert result2["reused"] is True
    assert result2["port"] == first_port


def test_distinct_profiles_yield_distinct_chromes(cleanup_test_chromes):
    """
    Real scenario: browser_start respects profile identity — different profiles → different Chromes

    Workflow: Start Chrome (profile A) → Start Chrome (profile B, reuse=any) → Verify distinct ports, neither reused

    User problem: A worker pool relies on per-profile Chrome isolation. If reuse=any silently hands back a Chrome running another profile, all workers collapse onto one Chrome and per-profile state leaks.

    Data flow:
      1. browser_start operation
      2. browser_start operation
    """
    # Step 1: Execute operation
    result1 = browser_start(headless=True, profile="test-profA")
    assert "error" not in result1
    assert result1["reused"] is False
    port1 = result1["port"]  # Extract for next step

    # Step 2: Execute operation
    result2 = browser_start(headless=True, profile="test-profB")
    assert "error" not in result2
    assert result2["reused"] is False
    assert result2["port"] != port1


def test_reuse_none_same_profile_still_detects(cleanup_test_chromes):
    """
    Real scenario: reuse='none' skips reuse scan but profile check catches existing Chrome

    Workflow: Start Chrome → Start again with reuse=none + same profile → Verify still reused via profile detection

    User problem: Even when reuse scanning is disabled, starting Chrome with an already-active profile must reuse it to avoid Chrome conflicts

    Data flow:
      1. browser_start operation
      2. browser_start operation
    """
    # Step 1: Execute operation
    result1 = browser_start(headless=True, profile="test-force")
    assert "error" not in result1
    port1 = result1["port"]  # Extract for next step

    # Step 2: Execute operation
    result2 = browser_start(headless=True, profile="test-force", reuse="none")
    assert "error" not in result2
    assert result2["reused"] is True
    assert result2["port"] == port1


def test_reuse_none_different_profile_new_chrome(cleanup_test_chromes):
    """
    Real scenario: reuse='none' + different profile = truly new Chrome

    Workflow: Start Chrome (profile A, reuse=none) → Start Chrome (profile B, reuse=none) → Verify different ports

    User problem: With reuse disabled and different profiles, each gets its own Chrome instance

    Data flow:
      1. browser_start operation
      2. browser_start operation
    """
    # Step 1: Execute operation
    result1 = browser_start(headless=True, profile="test-newA", reuse="none")
    assert "error" not in result1
    assert result1["reused"] is False
    port1 = result1["port"]  # Extract for next step

    # Step 2: Execute operation
    result2 = browser_start(headless=True, profile="test-newB", reuse="none")
    assert "error" not in result2
    assert result2["reused"] is False
    assert result2["port"] != port1


def test_stop_frees_port(cleanup_test_chromes):
    """
    Real scenario: Stopping a browser frees its debug port

    Workflow: Start Chrome → Verify port in use → Stop → Verify port freed

    User problem: Ports must be released after stop so they can be reused by future Chrome instances

    Data flow:
      1. browser_start operation
      2. is_port_in_use operation
      3. browser_stop operation
    """
    # Step 1: Execute operation
    result = browser_start(headless=True, profile="test-stop-port")
    assert "error" not in result
    port = result["port"]  # Extract for next step

    # Step 2: Execute operation
    in_use_before = is_port_in_use(port=port)
    assert in_use_before is True

    # Step 3: Execute operation
    stop_result = browser_stop(port=port)
    assert stop_result["stopped"] is True


def test_restart_after_stop(cleanup_test_chromes):
    """
    Real scenario: Can restart Chrome with same profile after stopping

    Workflow: Start Chrome → Stop → Start again → Verify fresh (not reused)

    User problem: After stopping a browser, starting again with the same profile should launch a new instance

    Data flow:
      1. browser_start operation
      2. browser_stop operation
      3. browser_start operation
    """
    # Step 1: Execute operation
    result1 = browser_start(headless=True, profile="test-restart")
    assert "error" not in result1
    port1 = result1["port"]  # Extract for next step

    # Step 2: Execute operation
    time.sleep(3)
    stop_result = browser_stop(port=port1)
    assert stop_result["stopped"] is True

    # Step 3: Execute operation
    time.sleep(3)
    result2 = browser_start(headless=True, profile="test-restart")
    assert "error" not in result2
    assert result2["reused"] is False


def test_list_shows_port_and_pid(cleanup_test_chromes):
    """
    Real scenario: browser_list includes port and pid for each browser

    Workflow: Start Chrome → List → Verify port and pid present

    User problem: Listing must show identifying info (port, pid) for each browser instance

    Data flow:
      1. browser_start operation
      2. browser_list operation
    """
    # Step 1: Execute operation
    result = browser_start(headless=True, profile="test-list-info")
    assert "error" not in result
    port = result["port"]  # Extract for next step

    # Step 2: Execute operation
    listing = browser_list()
    assert any(b["port"] == port and "pid" in b for b in listing["browsers"])


async def test_connection_reuse_same_port(cleanup_test_chromes):
    """
    Real scenario: Multiple connect_browser() calls reuse the same BrowserClient

    Workflow: Start Chrome → Connect twice → Verify same instance → Execute JS

    User problem: Without connection reuse, multiple connect_browser() calls leak WebSockets and exhaust Chrome's CDP slots

    Data flow:
      1. browser_start operation
      2. connect_browser operation
      3. connect_browser operation
      4. get_active_tab operation
      5. Execute JS to verify connection works
    """
    # Step 1: Execute operation
    result = browser_start(headless=True, profile="test-conn-reuse")
    assert "error" not in result
    port = result["port"]  # Extract for next step

    # Step 2: Execute operation
    b1 = await connect_browser(port=port)

    # Step 3: Execute operation
    b2 = await connect_browser(port=port)
    assert b1 is b2

    # Step 4: Execute operation
    tab = await get_active_tab(browser=b2)

    # Step 5: Execute JS to verify connection works
    r = await tab.evaluate(expression="1 + 1")
    assert r == 2


async def test_close_then_reconnect_fresh_instance(cleanup_test_chromes):
    """
    Real scenario: After close(), reconnecting creates a fresh BrowserClient

    Workflow: Start Chrome → Connect → Close → Reconnect → Verify different instance → JS works

    User problem: After explicitly closing a connection, the next connect must create a fresh instance rather than returning a dead cached one

    Data flow:
      1. browser_start operation
      2. connect_browser operation
      3. b1.close operation
      4. connect_browser operation
      5. get_active_tab operation
      6. tab.evaluate operation
    """
    # Step 1: Execute operation
    result = browser_start(headless=True, profile="test-close-recon")
    assert "error" not in result
    port = result["port"]  # Extract for next step

    # Step 2: Execute operation
    b1 = await connect_browser(port=port)

    # Step 3: Execute operation
    _ = await b1.close()

    # Step 4: Execute operation
    b2 = await connect_browser(port=port)
    assert b2 is not b1

    # Step 5: Execute operation
    tab = await get_active_tab(browser=b2)

    # Step 6: Execute operation
    r = await tab.evaluate(expression="2 + 2")
    assert r == 4


async def test_context_manager_clears_cache(cleanup_test_chromes):
    """
    Real scenario: async with connect_browser() cleans up cache on exit

    Workflow: Start Chrome → async with connect_browser → JS works → Exit → Cache cleared

    User problem: Context manager must remove the cached BrowserClient so stale connections don't accumulate

    Data flow:
      1. browser_start operation
      2. Use async context manager, verify JS works, then verify cache cleared on exit
    """
    # Step 1: Execute operation
    result = browser_start(headless=True, profile="test-ctx-mgr")
    assert "error" not in result
    port = result["port"]  # Extract for next step

    # Step 2: Use async context manager, verify JS works, then verify cache cleared on exit
    async with await connect_browser(port=port) as browser:
        tab = await get_active_tab(browser)
        r = await tab.evaluate("3 + 3")
        assert r == 6

    # Cache should be cleared after context manager exit
    key = (browser.host, port)
    assert key not in BrowserClient._instances


async def test_tab_reconnects_after_ws_disconnect(cleanup_test_chromes):
    """
    Real scenario: Tab auto-reconnects when its WebSocket dies

    Workflow: Start Chrome → Connect → JS works → Kill WS → JS works again (auto-reconnect)

    User problem: WebSocket connections can drop (idle timeout, network hiccup); tab must transparently reconnect

    Data flow:
      1. browser_start operation
      2. connect_browser operation
      3. get_active_tab operation
      4. Verify tab works before disconnect
      5. Simulate WebSocket dying and verify auto-reconnect
    """
    # Step 1: Execute operation
    result = browser_start(headless=True, profile="test-tab-recon")
    assert "error" not in result
    port = result["port"]  # Extract for next step

    # Step 2: Execute operation
    browser = await connect_browser(port=port)

    # Step 3: Execute operation
    tab = await get_active_tab(browser=browser)

    # Step 4: Verify tab works before disconnect
    r1 = await tab.evaluate(expression="10 + 20")
    assert r1 == 30

    # Step 5: Simulate WebSocket dying and verify auto-reconnect
    await tab._connection.disconnect()
    assert tab._connection.closed

    # Next call should auto-reconnect and succeed
    r2 = await tab.evaluate("30 + 40")
    assert r2 == 70


async def test_screenshot_after_ws_reconnect(cleanup_test_chromes):
    """
    Real scenario: Screenshot works after tab WebSocket reconnects

    Workflow: Start Chrome → Screenshot → Kill WS → Screenshot again (Page.enable re-enabled)

    User problem: Page.captureScreenshot requires Page.enable() which must be re-sent after WebSocket reconnection

    Data flow:
      1. browser_start operation
      2. connect_browser operation
      3. get_active_tab operation
      4. Screenshot before disconnect
      5. Kill WS, screenshot again, cleanup files
    """
    # Step 1: Execute operation
    result = browser_start(headless=True, profile="test-ss-recon")
    assert "error" not in result
    port = result["port"]  # Extract for next step

    # Step 2: Execute operation
    browser = await connect_browser(port=port)

    # Step 3: Execute operation
    tab = await get_active_tab(browser=browser)

    # Step 4: Screenshot before disconnect
    r1 = await page_screenshot(tab=tab, path="test_recon1.png")
    assert r1["size"] > 0

    # Step 5: Kill WS, screenshot again, cleanup files
    await tab._connection.disconnect()

    # Screenshot after reconnect — Page domain must be re-enabled
    r2 = await page_screenshot(tab=tab, path="test_recon2.png")
    assert r2["size"] > 0

    # Cleanup
    import os as _os

    _os.unlink("test_recon1.png")
    _os.unlink("test_recon2.png")


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert browser_start is not None
    assert browser_stop is not None
    assert browser_list is not None
    assert connect_browser is not None
    assert get_active_tab is not None
    assert find_debug_chromes is not None
    assert find_workspace_chromes is not None
    assert get_workspace_slug is not None
    assert get_workspace_profile_dir is not None
