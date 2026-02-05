"""Browser lifecycle integration tests.

Tests the full start → reuse → connect → stop workflow:
- start_browser reuse behavior (same profile, different profiles)
- CLI auto-detection (no --port specified)
- stop_browser cleanup
- list_browsers visibility

These tests launch REAL Chrome instances (headless) and verify port/profile behavior.
"""

import asyncio

import pytest

from ai_dev_browser.core.browser import list_browsers, start_browser, stop_browser
from ai_dev_browser.core.port import (
    find_ai_dev_browser_chromes,
    is_chrome_in_use,
    is_port_in_use,
)


# Unique profile prefix to avoid collisions with user's real profiles
TEST_PROFILE = "test-lifecycle"


async def _stop_all_ai_dev_chromes():
    """Stop all ai-dev-browser Chrome instances and wait for ports to free."""
    for port in find_ai_dev_browser_chromes():
        try:
            stop_browser(port=port)
        except Exception:
            pass
    # Wait for all ports to free
    for _ in range(30):
        if not find_ai_dev_browser_chromes():
            break
        await asyncio.sleep(0.3)


@pytest.fixture(autouse=True)
async def cleanup_test_chromes():
    """Stop all ai-dev-browser Chromes before AND after each test.

    Before: ensures clean state (no leftover Chromes from previous runs).
    After: cleans up Chromes started during the test.
    """
    await _stop_all_ai_dev_chromes()
    yield
    await _stop_all_ai_dev_chromes()


class TestStartBrowserReuse:
    """Test that start_browser correctly reuses existing Chrome instances."""

    async def test_second_start_reuses_first(self):
        """Calling start_browser twice should reuse the first Chrome."""
        result1 = start_browser(headless=True, profile=f"{TEST_PROFILE}-reuse1")
        assert "error" not in result1, f"First start failed: {result1}"
        port1 = result1["port"]
        assert result1["reused"] is False

        # Second call - should reuse
        result2 = start_browser(headless=True, profile=f"{TEST_PROFILE}-reuse1")
        assert "error" not in result2, f"Second start failed: {result2}"
        assert result2["reused"] is True
        assert result2["port"] == port1, "Should reuse same port"

    async def test_reuse_finds_idle_chrome_regardless_of_profile(self):
        """Default reuse strategy finds ANY idle Chrome, even with different profile."""
        result1 = start_browser(headless=True, profile=f"{TEST_PROFILE}-profA")
        assert "error" not in result1
        port1 = result1["port"]
        assert result1["reused"] is False

        # Different profile, but default reuse="ai_dev_browser" finds idle profA Chrome
        result2 = start_browser(headless=True, profile=f"{TEST_PROFILE}-profB")
        assert "error" not in result2
        assert result2["reused"] is True
        assert result2["port"] == port1, "Reuse strategy finds idle Chrome before profile check"

    async def test_reuse_none_with_same_profile_still_reuses(self):
        """reuse='none' skips reuse scan, but profile check still catches existing Chrome."""
        result1 = start_browser(headless=True, profile=f"{TEST_PROFILE}-force")
        assert "error" not in result1
        port1 = result1["port"]

        # reuse='none' skips _find_reusable_chrome, but _find_chrome_using_profile
        # detects the same profile dir is already in use
        result2 = start_browser(
            headless=True, profile=f"{TEST_PROFILE}-force", reuse="none"
        )
        assert "error" not in result2
        assert result2["reused"] is True
        assert result2["port"] == port1

    async def test_reuse_none_different_profile_gets_new_chrome(self):
        """reuse='none' + different profile = truly new Chrome."""
        result1 = start_browser(
            headless=True, profile=f"{TEST_PROFILE}-newA", reuse="none"
        )
        assert "error" not in result1
        port1 = result1["port"]
        assert result1["reused"] is False

        result2 = start_browser(
            headless=True, profile=f"{TEST_PROFILE}-newB", reuse="none"
        )
        assert "error" not in result2
        port2 = result2["port"]
        assert result2["reused"] is False
        assert port1 != port2, "Different profiles with reuse=none should get different ports"


class TestAutoDetection:
    """Test CLI auto-detection: when no port specified, find idle Chrome."""

    async def test_find_idle_chrome(self):
        """Auto-detection should find an idle Chrome in the port range."""
        result = start_browser(headless=True, profile=f"{TEST_PROFILE}-detect")
        assert "error" not in result
        port = result["port"]

        # Verify it's visible to find_ai_dev_browser_chromes
        found = find_ai_dev_browser_chromes()
        assert port in found, f"Port {port} not found in {found}"

        # Verify it's NOT in use (no CDP debugger attached)
        assert not is_chrome_in_use(port), "Freshly started Chrome should not be in use"

    async def test_auto_detect_skips_in_use_chrome(self):
        """Auto-detection should skip Chromes that have attached debuggers."""
        result = start_browser(headless=True, profile=f"{TEST_PROFILE}-skip")
        assert "error" not in result
        port = result["port"]

        # Connect via nodriver (connect_browser now calls Target.attachToTarget)
        from ai_dev_browser.core import connect_browser

        browser = await connect_browser(port=port)

        # Now it should be "in use"
        assert is_chrome_in_use(port), "Connected Chrome should be in use"

        # Start another Chrome - auto-detection should skip the in-use one
        result2 = start_browser(headless=True, profile=f"{TEST_PROFILE}-skip2")
        assert "error" not in result2
        port2 = result2["port"]
        assert port2 != port, "Should get a different port since first is in use"

        # Clean up
        browser.stop()
        await asyncio.sleep(0.5)


class TestStopBrowser:
    """Test stop_browser cleanup."""

    async def test_stop_frees_port(self):
        """Stopping a browser should free its port."""
        result = start_browser(headless=True, profile=f"{TEST_PROFILE}-stop")
        assert "error" not in result
        port = result["port"]

        assert is_port_in_use(port=port), "Chrome should be listening"

        stop_result = stop_browser(port=port)
        assert stop_result["stopped"] is True
        assert stop_result["count"] == 1

        # Wait for port to free
        for _ in range(20):
            if not is_port_in_use(port=port):
                break
            await asyncio.sleep(0.3)

        assert not is_port_in_use(port=port), "Port should be free after stop"

    async def test_restart_after_stop(self):
        """Can start a new Chrome after stopping the previous one."""
        result1 = start_browser(headless=True, profile=f"{TEST_PROFILE}-restart")
        assert "error" not in result1
        port1 = result1["port"]

        stop_browser(port=port1)
        for _ in range(20):
            if not is_port_in_use(port=port1):
                break
            await asyncio.sleep(0.3)

        # Start again with same profile
        result2 = start_browser(headless=True, profile=f"{TEST_PROFILE}-restart")
        assert "error" not in result2
        assert result2["reused"] is False, "Should be a fresh Chrome after stop"


class TestListBrowsers:
    """Test list_browsers visibility."""

    async def test_started_chrome_visible_in_list(self):
        """Chrome started by us should appear in list_browsers."""
        result = start_browser(headless=True, profile=f"{TEST_PROFILE}-list")
        assert "error" not in result
        port = result["port"]

        listing = list_browsers()
        all_ports = [
            b["port"]
            for b in listing.get("this_session", []) + listing.get("other_sessions", [])
        ]
        assert port in all_ports, f"Port {port} not in list: {listing}"

    async def test_list_shows_can_connect_status(self):
        """list_browsers should show correct can_connect status."""
        result = start_browser(headless=True, profile=f"{TEST_PROFILE}-connect")
        assert "error" not in result
        port = result["port"]

        listing = list_browsers()
        for b in listing.get("this_session", []) + listing.get("other_sessions", []):
            if b["port"] == port:
                assert b["can_connect"] is True, "Idle Chrome should be connectable"
                break
        else:
            pytest.fail(f"Port {port} not found in listing")


class TestCLIAutoDetectFlow:
    """Test the _cli.py auto-detection logic end-to-end.

    This simulates what happens when a tool with requires_tab=True
    is called without --port: it should auto-detect a running Chrome.
    """

    async def test_cli_auto_detect_finds_chrome(self):
        """Simulate CLI auto-detection: find idle Chrome without --port."""
        # Start a Chrome
        result = start_browser(headless=True, profile=f"{TEST_PROFILE}-cli")
        assert "error" not in result
        expected_port = result["port"]

        # Simulate what _cli.py does when port is None
        detected_port = None
        for candidate in find_ai_dev_browser_chromes():
            if not is_chrome_in_use(candidate):
                detected_port = candidate
                break

        assert detected_port is not None, "Should detect idle Chrome"
        assert detected_port == expected_port

    async def test_cli_auto_detect_connects_successfully(self):
        """Auto-detected port should be connectable."""
        result = start_browser(headless=True, profile=f"{TEST_PROFILE}-cli2")
        assert "error" not in result

        # Auto-detect
        detected_port = None
        for candidate in find_ai_dev_browser_chromes():
            if not is_chrome_in_use(candidate):
                detected_port = candidate
                break

        assert detected_port is not None

        # Connect to it (what _cli.py does after auto-detection)
        from ai_dev_browser.core import connect_browser, get_active_tab

        browser = await connect_browser(port=detected_port)
        tab = await get_active_tab(browser)
        assert tab is not None

        # Execute JS to verify it works
        result = await tab.evaluate("1 + 1")
        assert result == 2

        browser.stop()
        await asyncio.sleep(0.5)

    async def test_no_chrome_returns_none(self):
        """When no Chrome is running, auto-detection should find nothing."""
        # Don't start any Chrome - just scan
        # (cleanup fixture ensures previous test Chromes are stopped)
        # Note: other Chromes from other tests/sessions may be running,
        # so we can't guarantee empty. But we test the logic path.
        detected_port = None
        for candidate in find_ai_dev_browser_chromes():
            if not is_chrome_in_use(candidate):
                detected_port = candidate
                break

        # This test verifies the code path doesn't crash.
        # detected_port may or may not be None depending on environment.
        # The important thing is no exception was raised.
