"""Browser lifecycle integration tests.

Tests the full start -> reuse -> connect -> stop workflow:
- browser_start reuse behavior (same profile, different profiles)
- CLI auto-detection (no --port specified)
- browser_stop cleanup
- browser_list visibility

These tests launch REAL Chrome instances (headless) and verify port/profile behavior.
"""

import asyncio

import pytest

from ai_dev_browser.core.browser import browser_list, browser_start, browser_stop
from ai_dev_browser.core.port import (
    find_debug_chromes,
    is_chrome_in_use,
    is_port_in_use,
)


# Unique profile prefix to avoid collisions with user's real profiles
TEST_PROFILE = "test-lifecycle"


def _stop_chrome_on_port(port: int):
    """Stop a specific Chrome and wait for port to free."""
    browser_stop(port=port)


@pytest.fixture(autouse=True)
async def track_and_cleanup_test_chromes():
    """Track Chromes started during each test and clean up only those.

    Records which debug Chromes exist before the test. After the test,
    stops only the NEW ones (started during the test).
    """
    # Record pre-existing Chromes
    existing_ports = {p for p, _pid in find_debug_chromes()}
    yield
    # Stop only Chromes that were started during this test
    for port, _pid in find_debug_chromes():
        if port not in existing_ports:
            _stop_chrome_on_port(port)
    # Wait for cleanup
    for _ in range(20):
        current = {p for p, _ in find_debug_chromes()}
        if current <= existing_ports:
            break
        await asyncio.sleep(0.3)


class TestStartBrowserReuse:
    """Test that browser_start correctly reuses existing Chrome instances."""

    async def test_second_start_reuses_first(self):
        """Calling browser_start twice should reuse the first Chrome."""
        result1 = browser_start(headless=True, profile=f"{TEST_PROFILE}-reuse1")
        assert "error" not in result1, f"First start failed: {result1}"
        port1 = result1["port"]
        assert result1["reused"] is False

        # Second call - should reuse
        result2 = browser_start(headless=True, profile=f"{TEST_PROFILE}-reuse1")
        assert "error" not in result2, f"Second start failed: {result2}"
        assert result2["reused"] is True
        assert result2["port"] == port1, "Should reuse same port"

    async def test_reuse_finds_idle_chrome_regardless_of_profile(self):
        """Default reuse strategy finds ANY idle Chrome, even with different profile."""
        result1 = browser_start(headless=True, profile=f"{TEST_PROFILE}-profA")
        assert "error" not in result1
        port1 = result1["port"]
        assert result1["reused"] is False

        # Different profile, but default reuse="any" finds idle profA Chrome
        result2 = browser_start(headless=True, profile=f"{TEST_PROFILE}-profB")
        assert "error" not in result2
        assert result2["reused"] is True
        assert result2["port"] == port1, (
            "Reuse strategy finds idle Chrome before profile check"
        )

    async def test_reuse_none_with_same_profile_still_reuses(self):
        """reuse='none' skips reuse scan, but profile check still catches existing Chrome."""
        result1 = browser_start(headless=True, profile=f"{TEST_PROFILE}-force")
        assert "error" not in result1
        port1 = result1["port"]

        # reuse='none' skips _find_reusable_chrome, but _find_chrome_using_profile
        # detects the same profile dir is already in use
        result2 = browser_start(
            headless=True, profile=f"{TEST_PROFILE}-force", reuse="none"
        )
        assert "error" not in result2
        assert result2["reused"] is True
        assert result2["port"] == port1

    async def test_reuse_none_different_profile_gets_new_chrome(self):
        """reuse='none' + different profile = truly new Chrome."""
        result1 = browser_start(
            headless=True, profile=f"{TEST_PROFILE}-newA", reuse="none"
        )
        assert "error" not in result1
        port1 = result1["port"]
        assert result1["reused"] is False

        result2 = browser_start(
            headless=True, profile=f"{TEST_PROFILE}-newB", reuse="none"
        )
        assert "error" not in result2
        port2 = result2["port"]
        assert result2["reused"] is False
        assert port1 != port2, (
            "Different profiles with reuse=none should get different ports"
        )


class TestAutoDetection:
    """Test CLI auto-detection: when no port specified, page_discover idle Chrome."""

    async def test_find_idle_chrome(self):
        """Auto-detection should page_discover an idle Chrome in the port range."""
        result = browser_start(headless=True, profile=f"{TEST_PROFILE}-detect")
        assert "error" not in result
        port = result["port"]

        # Verify it's visible to find_debug_chromes
        found_ports = [p for p, _pid in find_debug_chromes()]
        assert port in found_ports, f"Port {port} not found in {found_ports}"

        # Verify it's NOT in use (no CDP debugger attached)
        assert not is_chrome_in_use(port), "Freshly started Chrome should not be in use"

    async def test_auto_detect_skips_in_use_chrome(self):
        """Auto-detection should skip Chromes that have attached debuggers."""
        result = browser_start(headless=True, profile=f"{TEST_PROFILE}-skip")
        assert "error" not in result
        port = result["port"]

        # Connect (connect_browser calls Target.attachToTarget)
        from ai_dev_browser.core import connect_browser

        browser = await connect_browser(port=port)
        assert browser is not None, "Should connect successfully"

        # Now it should be "in use"
        assert is_chrome_in_use(port), "Connected Chrome should be in use"

        # Start another Chrome - auto-detection should skip the in-use one
        result2 = browser_start(headless=True, profile=f"{TEST_PROFILE}-skip2")
        assert "error" not in result2
        port2 = result2["port"]
        assert port2 != port, "Should get a different port since first is in use"


class TestStopBrowser:
    """Test browser_stop cleanup."""

    async def test_stop_frees_port(self):
        """Stopping a browser should free its port."""
        result = browser_start(headless=True, profile=f"{TEST_PROFILE}-stop")
        assert "error" not in result
        port = result["port"]

        assert is_port_in_use(port=port), "Chrome should be listening"

        stop_result = browser_stop(port=port)
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
        result1 = browser_start(headless=True, profile=f"{TEST_PROFILE}-restart")
        assert "error" not in result1
        port1 = result1["port"]

        browser_stop(port=port1)
        for _ in range(20):
            if not is_port_in_use(port=port1):
                break
            await asyncio.sleep(0.3)

        # Start again with same profile
        result2 = browser_start(headless=True, profile=f"{TEST_PROFILE}-restart")
        assert "error" not in result2
        assert result2["reused"] is False, "Should be a fresh Chrome after stop"


class TestListBrowsers:
    """Test browser_list visibility."""

    async def test_started_chrome_visible_in_list(self):
        """Chrome started by us should appear in browser_list."""
        result = browser_start(headless=True, profile=f"{TEST_PROFILE}-list")
        assert "error" not in result
        port = result["port"]

        listing = browser_list()
        all_ports = [b["port"] for b in listing.get("browsers", [])]
        assert port in all_ports, f"Port {port} not in list: {listing}"

    async def test_list_shows_can_connect_status(self):
        """browser_list should show correct can_connect status."""
        result = browser_start(headless=True, profile=f"{TEST_PROFILE}-connect")
        assert "error" not in result
        port = result["port"]

        listing = browser_list()
        for b in listing.get("browsers", []):
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
        """Simulate CLI auto-detection: page_discover idle Chrome without --port."""
        # Start a Chrome
        result = browser_start(headless=True, profile=f"{TEST_PROFILE}-cli")
        assert "error" not in result
        expected_port = result["port"]

        # Simulate what _cli.py does when port is None
        detected_port = None
        for candidate, _pid in find_debug_chromes():
            if not is_chrome_in_use(candidate):
                detected_port = candidate
                break

        assert detected_port is not None, "Should detect idle Chrome"
        assert detected_port == expected_port

    async def test_cli_auto_detect_connects_successfully(self):
        """Auto-detected port should be connectable."""
        result = browser_start(headless=True, profile=f"{TEST_PROFILE}-cli2")
        assert "error" not in result

        # Auto-detect
        detected_port = None
        for candidate, _pid in find_debug_chromes():
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

    async def test_no_chrome_returns_none(self):
        """When no Chrome is running, auto-detection should page_discover nothing."""
        for candidate, _pid in find_debug_chromes():
            if not is_chrome_in_use(candidate):
                break

        # This test verifies the code path doesn't crash.
        # detected_port may or may not be None depending on environment.


class TestConnectionReuse:
    """Test that repeated connect_browser() reuses connections.

    Covers the bug: multiple connect_browser() calls leak WebSockets,
    eventually exhausting Chrome's CDP slots and causing timeouts.
    """

    async def test_repeated_connect_reuses_instance(self):
        """Multiple connect_browser() to same port returns same instance."""
        result = browser_start(headless=True, profile=f"{TEST_PROFILE}-reuse-conn")
        assert "error" not in result
        port = result["port"]

        from ai_dev_browser.core.connection import connect_browser, get_active_tab

        b1 = await connect_browser(port=port)
        b2 = await connect_browser(port=port)
        assert b1 is b2, "Should reuse same BrowserClient"

        # Both should work
        tab = await get_active_tab(b2)
        r = await tab.evaluate("1 + 1")
        assert r == 2

    async def test_close_then_reconnect(self):
        """After close(), next connect_browser() creates fresh instance."""
        result = browser_start(headless=True, profile=f"{TEST_PROFILE}-close-recon")
        assert "error" not in result
        port = result["port"]

        from ai_dev_browser.core.connection import connect_browser, get_active_tab

        b1 = await connect_browser(port=port)
        await b1.close()

        b2 = await connect_browser(port=port)
        assert b2 is not b1, "Should create new instance after close"

        tab = await get_active_tab(b2)
        r = await tab.evaluate("2 + 2")
        assert r == 4

    async def test_context_manager_cleanup(self):
        """async with connect_browser() cleans up on exit."""
        result = browser_start(headless=True, profile=f"{TEST_PROFILE}-ctx")
        assert "error" not in result
        port = result["port"]

        from ai_dev_browser.core.connection import (
            BrowserClient,
            connect_browser,
            get_active_tab,
        )

        async with await connect_browser(port=port) as browser:
            tab = await get_active_tab(browser)
            r = await tab.evaluate("3 + 3")
            assert r == 6

        # Cache should be cleared
        key = (browser.host, port)
        assert key not in BrowserClient._instances

    async def test_repeated_connect_all_work(self):
        """5 sequential connect_browser() calls all produce working tabs."""
        result = browser_start(headless=True, profile=f"{TEST_PROFILE}-multi")
        assert "error" not in result
        port = result["port"]

        from ai_dev_browser.core.connection import connect_browser, get_active_tab

        for i in range(5):
            browser = await connect_browser(port=port)
            tab = await get_active_tab(browser)
            r = await tab.evaluate(f"{i} + 1")
            assert r == i + 1, f"Iteration {i}: expected {i + 1}, got {r}"

    async def test_tab_reconnects_after_websocket_disconnect(self):
        """Tab auto-reconnects when its WebSocket is broken."""
        result = browser_start(headless=True, profile=f"{TEST_PROFILE}-tab-recon")
        assert "error" not in result
        port = result["port"]

        from ai_dev_browser.core.connection import connect_browser, get_active_tab

        browser = await connect_browser(port=port)
        tab = await get_active_tab(browser)

        # Verify tab works
        r = await tab.evaluate("10 + 20")
        assert r == 30

        # Simulate tab WebSocket dying (e.g., Electron idle timeout)
        await tab._connection.disconnect()
        assert tab._connection.closed

        # Next call should auto-reconnect and succeed
        r2 = await tab.evaluate("30 + 40")
        assert r2 == 70

    async def test_screenshot_works_after_reconnect(self):
        """Page.captureScreenshot requires Page.enable() after reconnect."""
        result = browser_start(headless=True, profile=f"{TEST_PROFILE}-ss-recon")
        assert "error" not in result
        port = result["port"]

        from ai_dev_browser.core.connection import connect_browser, get_active_tab
        from ai_dev_browser.core.page import page_screenshot

        browser = await connect_browser(port=port)
        tab = await get_active_tab(browser)

        # Screenshot before disconnect
        r1 = await page_screenshot(tab, path="test_recon1.png")
        assert r1["size"] > 0

        # Kill tab WebSocket
        await tab._connection.disconnect()

        # Screenshot after reconnect — Page domain must be re-enabled
        r2 = await page_screenshot(tab, path="test_recon2.png")
        assert r2["size"] > 0

        import os

        os.unlink("test_recon1.png")
        os.unlink("test_recon2.png")
