"""Integration tests for window operations."""

import asyncio

from ai_dev_browser.core import focus_window, resize_window


class TestResizeWindow:
    """Test window resize operations."""

    async def test_resize_window_returns_dict(self, browser):
        """Should resize window and return dict with dimensions."""
        tab = browser.main_tab

        result = await resize_window(tab, width=800, height=600)
        assert isinstance(result, dict)
        assert result.get("width") == 800
        assert result.get("height") == 600

    async def test_resize_window_updates_size(self, browser):
        """Should actually change window dimensions."""
        tab = browser.main_tab

        await resize_window(tab, width=1024, height=768)
        await asyncio.sleep(0.2)

        # Check via JavaScript
        width = await tab.evaluate("window.innerWidth")
        height = await tab.evaluate("window.innerHeight")

        # Allow some tolerance for browser chrome
        assert abs(width - 1024) < 50
        assert abs(height - 768) < 100


class TestFocusWindow:
    """Test window focus operations."""

    async def test_focus_window_returns_dict(self, browser):
        """Should return dict with focused status."""
        tab = browser.main_tab

        result = await focus_window(tab)
        assert isinstance(result, dict)
        assert result.get("focused") is True
