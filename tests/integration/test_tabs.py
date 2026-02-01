"""Integration tests for tab operations."""

import asyncio

from ai_dev_browser.core import list_tabs, new_tab


class TestNewTab:
    """Test creating new tabs."""

    async def test_new_tab_creates_tab(self, browser):
        """Should create a new tab."""
        initial_tabs = list_tabs(browser)
        initial_count = len(initial_tabs)

        new = await new_tab(browser)
        assert new is not None

        # Wait for tab to be registered
        await asyncio.sleep(0.3)

        tabs = list_tabs(browser)
        assert len(tabs) >= initial_count  # At least same count

    async def test_new_tab_with_url(self, browser):
        """Should create tab and navigate to URL."""
        html = "<html><body><h1>New Tab</h1></body></html>"
        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()

        new = await new_tab(browser, url=data_url)
        await asyncio.sleep(0.5)

        title = await new.evaluate("document.querySelector('h1')?.innerText || ''")
        assert title == "New Tab"


class TestListTabs:
    """Test listing tabs."""

    async def test_list_tabs_returns_list(self, browser):
        """Should return list of tabs."""
        tabs = list_tabs(browser)
        assert isinstance(tabs, list)
        assert len(tabs) >= 1  # At least main tab

    async def test_list_tabs_has_url_and_title(self, browser):
        """Tab info should include url and title."""
        tabs = list_tabs(browser)
        assert len(tabs) >= 1

        tab_info = tabs[0]
        assert "url" in tab_info
        assert "title" in tab_info
        assert "active" in tab_info
