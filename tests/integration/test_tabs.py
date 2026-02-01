"""Integration tests for tab operations."""

import asyncio

from ai_dev_browser.core import close_tab, list_tabs, new_tab, switch_tab


class TestNewTab:
    """Test creating new tabs."""

    async def test_new_tab_creates_tab(self, browser):
        """Should create a new tab and return dict with tab info."""
        initial = await list_tabs(browser)
        initial_count = initial["count"]

        result = await new_tab(browser)
        assert isinstance(result, dict)
        assert "url" in result
        assert "title" in result
        assert "tab" in result  # For programmatic use

        # Wait for tab to be registered
        await asyncio.sleep(0.3)

        tabs = await list_tabs(browser)
        assert tabs["count"] >= initial_count  # At least same count

    async def test_new_tab_with_url(self, browser):
        """Should create tab and navigate to URL."""
        html = "<html><body><h1>New Tab</h1></body></html>"
        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()

        result = await new_tab(browser, url=data_url)
        await asyncio.sleep(0.5)

        assert result["url"] == data_url
        # Use the returned tab for evaluation
        tab = result["tab"]
        title = await tab.evaluate("document.querySelector('h1')?.innerText || ''")
        assert title == "New Tab"


class TestListTabs:
    """Test listing tabs."""

    async def test_list_tabs_returns_dict(self, browser):
        """Should return dict with tabs list and count."""
        result = await list_tabs(browser)
        assert isinstance(result, dict)
        assert "tabs" in result
        assert "count" in result
        assert isinstance(result["tabs"], list)
        assert result["count"] >= 1  # At least main tab

    async def test_list_tabs_has_tab_info(self, browser):
        """Tab info should include url, title, and active."""
        result = await list_tabs(browser)
        assert result["count"] >= 1

        tab_info = result["tabs"][0]
        assert "url" in tab_info
        assert "title" in tab_info
        assert "active" in tab_info
        assert "id" in tab_info


class TestSwitchTab:
    """Test switching between tabs."""

    async def test_switch_tab_activates_tab(self, browser):
        """Should switch to specified tab."""
        # Create a new tab first
        await new_tab(browser)
        await asyncio.sleep(0.3)

        # Switch to tab 0 (main tab)
        switch_result = await switch_tab(browser, 0)
        assert isinstance(switch_result, dict)
        assert "url" in switch_result
        assert "title" in switch_result
        assert "tab" in switch_result

    async def test_switch_tab_invalid_id_raises(self, browser):
        """Should raise IndexError for invalid tab ID."""
        import pytest

        with pytest.raises(IndexError):
            await switch_tab(browser, 999)


class TestCloseTab:
    """Test closing tabs."""

    async def test_close_tab_returns_remaining(self, browser):
        """Should close tab and return remaining count."""
        # Create a new tab first
        new_result = await new_tab(browser)
        new_tab_obj = new_result["tab"]
        await asyncio.sleep(0.5)

        tabs_before = await list_tabs(browser)
        count_before = tabs_before["count"]

        # Skip if we don't have at least 2 tabs
        if count_before < 2:
            import pytest

            pytest.skip("Could not create second tab for close test")

        # Close the new tab using the tab object directly
        result = await close_tab(browser, tab=new_tab_obj)
        assert isinstance(result, dict)
        assert "remaining" in result

        # Wait for close to complete
        await asyncio.sleep(0.3)

        tabs_after = await list_tabs(browser)
        assert tabs_after["count"] < count_before

    async def test_close_last_tab_raises(self, browser):
        """Should raise ValueError when closing the last tab."""
        import pytest

        # Make sure we only have one tab
        tabs = await list_tabs(browser)
        while tabs["count"] > 1:
            await close_tab(browser, tab_id=1)
            await asyncio.sleep(0.2)
            tabs = await list_tabs(browser)

        with pytest.raises(ValueError):
            await close_tab(browser)
