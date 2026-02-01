"""Integration tests for navigation operations."""

import asyncio

from ai_dev_browser.core import get_page_info, goto, reload, wait_for_url


class TestGoto:
    """Test page navigation."""

    async def test_goto_data_url(self, browser):
        """Should navigate to data URL."""
        tab = browser.main_tab

        html = "<html><body><h1>Test Page</h1></body></html>"
        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()

        await goto(tab, data_url)
        await asyncio.sleep(0.2)

        title = await tab.evaluate("document.querySelector('h1').innerText")
        assert title == "Test Page"

    async def test_goto_updates_url(self, browser):
        """Navigation should update current URL."""
        tab = browser.main_tab

        await goto(tab, "about:blank")
        await asyncio.sleep(0.2)

        info = await get_page_info(tab)
        assert "about:blank" in info["url"]


class TestReload:
    """Test page reload."""

    async def test_reload_preserves_url(self, browser):
        """Reload should stay on same URL."""
        tab = browser.main_tab

        html = "<html><body><div id='counter'>0</div></body></html>"
        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()

        await goto(tab, data_url)
        await asyncio.sleep(0.2)

        # Modify DOM
        await tab.evaluate("document.getElementById('counter').innerText = '999'")
        modified = await tab.evaluate("document.getElementById('counter').innerText")
        assert modified == "999"

        # Reload should reset
        await reload(tab)
        await asyncio.sleep(0.3)

        reset = await tab.evaluate("document.getElementById('counter').innerText")
        assert reset == "0"


class TestWaitForUrl:
    """Test URL waiting."""

    async def test_wait_for_url_pattern(self, browser):
        """Should wait for URL matching pattern."""
        tab = browser.main_tab

        # Navigate to about:blank first
        await goto(tab, "about:blank")
        await asyncio.sleep(0.2)

        # Wait for URL should pass immediately for current URL
        result = await wait_for_url(tab, pattern="about:blank", timeout=5)
        assert result["matched"] is True


class TestPageInfo:
    """Test page info retrieval."""

    async def test_get_page_info(self, browser):
        """Should return page URL and title."""
        tab = browser.main_tab

        html = "<html><head><title>Test Title</title></head><body></body></html>"
        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()

        await goto(tab, data_url)
        await asyncio.sleep(0.2)

        info = await get_page_info(tab)
        assert "url" in info
        assert "title" in info
        assert info["title"] == "Test Title"
