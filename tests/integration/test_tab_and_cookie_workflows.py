"""Tab management and cookie/session persistence workflows.

Covers:
- Tab lifecycle: create → navigate → switch → verify → close
- Multi-tab state isolation: tab1 state vs tab2 state
- Cookie persistence: save → reload → verify
- Cookie filtering and clearing
"""

import asyncio
import base64
import json
import tempfile
from pathlib import Path

from ai_dev_browser.core import (
    close_tab,
    list_tabs,
    load_cookies,
    new_tab,
    save_cookies,
    switch_tab,
)


def make_data_url(html: str) -> str:
    return "data:text/html;base64," + base64.b64encode(html.encode()).decode()


async def eval_json(tab, js_expr):
    result = await tab.evaluate(f"JSON.stringify({js_expr})")
    if result is None or result == "null":
        return None
    return json.loads(result)


class TestTabLifecycleWorkflow:
    """Tab create → navigate → switch → verify → close."""

    async def test_create_navigate_switch_close(self, browser):
        """Full tab lifecycle: create tab, navigate, switch back, close."""
        tab1 = browser.main_tab

        # Navigate tab1
        page1_html = make_data_url("<html><body><h1>Tab 1</h1></body></html>")
        await tab1.get(page1_html)
        await asyncio.sleep(0.3)

        # Create tab2 and navigate
        result = await new_tab(browser)
        tab2 = result["tab"]
        page2_html = make_data_url("<html><body><h1>Tab 2</h1></body></html>")
        await tab2.get(page2_html)
        await asyncio.sleep(0.3)

        # Verify tab2 content
        content2 = await tab2.evaluate("document.body.innerText")
        assert "Tab 2" in content2

        # List tabs — should have at least 2
        tabs_result = await list_tabs(browser)
        assert tabs_result["count"] >= 2

        # Switch back to tab1
        switch_result = await switch_tab(browser, tab_id=0)
        assert switch_result is not None

        # Close tab2
        close_result = await close_tab(browser, tab=tab2)
        assert close_result["remaining"] >= 1

    async def test_tabs_have_independent_urls(self, browser):
        """Each tab navigates independently."""
        tab1 = browser.main_tab

        url1 = make_data_url("<html><body>Page A</body></html>")
        url2 = make_data_url("<html><body>Page B</body></html>")

        await tab1.get(url1)
        await asyncio.sleep(0.2)

        result = await new_tab(browser)
        tab2 = result["tab"]
        await tab2.get(url2)
        await asyncio.sleep(0.2)

        # Verify different content
        text1 = await tab1.evaluate("document.body.innerText")
        text2 = await tab2.evaluate("document.body.innerText")
        assert "Page A" in text1
        assert "Page B" in text2

        await close_tab(browser, tab=tab2)


class TestMultiTabInteractionWorkflow:
    """Multi-tab interaction: operate on multiple tabs, verify state isolation."""

    async def test_multi_tab_state_isolation(self, browser):
        """JS state in one tab does not leak to another."""
        tab1 = browser.main_tab

        html = make_data_url("""<html><body>
            <script>window.tabState = 'unset';</script>
        </body></html>""")

        # Tab1: set state
        await tab1.get(html)
        await asyncio.sleep(0.2)
        await tab1.evaluate("window.tabState = 'tab1_value'")

        # Tab2: set different state
        result = await new_tab(browser)
        tab2 = result["tab"]
        await tab2.get(html)
        await asyncio.sleep(0.2)
        await tab2.evaluate("window.tabState = 'tab2_value'")

        # Verify isolation
        state1 = await tab1.evaluate("window.tabState")
        state2 = await tab2.evaluate("window.tabState")
        assert state1 == "tab1_value"
        assert state2 == "tab2_value"

        await close_tab(browser, tab=tab2)

    async def test_open_tab_navigate_switch_back_verify(self, browser):
        """Open second tab, do work, switch back to first, verify first is unchanged."""
        tab1 = browser.main_tab

        html1 = make_data_url(
            "<html><body><div id='marker'>Original</div></body></html>"
        )
        await tab1.get(html1)
        await asyncio.sleep(0.2)

        # Set state in tab1
        await tab1.evaluate(
            "document.getElementById('marker').textContent = 'Modified by tab1'"
        )

        # Open tab2, do something
        result = await new_tab(browser)
        tab2 = result["tab"]
        html2 = make_data_url("<html><body>Tab 2 content</body></html>")
        await tab2.get(html2)
        await asyncio.sleep(0.2)

        # Switch back to tab1
        await switch_tab(browser, tab_id=0)

        # Tab1 state should be preserved
        marker_text = await tab1.evaluate(
            "document.getElementById('marker').textContent"
        )
        assert marker_text == "Modified by tab1"

        await close_tab(browser, tab=tab2)


class TestCookiePersistenceWorkflow:
    """Cookie save → load → verify workflow."""

    async def test_save_and_load_cookies(self, browser):
        """Save cookies to file → verify file → load back."""
        tab = browser.main_tab

        # Use the browser's cookie API directly (no network needed)
        # First save whatever cookies exist (even if empty, tests the mechanism)
        with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as f:
            cookie_path = f.name

        try:
            save_result = await save_cookies(tab, path=cookie_path)
            assert save_result.get("saved") is True

            # File should exist
            assert Path(cookie_path).exists()

            # Load back (should not error)
            load_result = await load_cookies(tab, path=cookie_path)
            assert load_result.get("loaded") is True
        finally:
            Path(cookie_path).unlink(missing_ok=True)

    async def test_cookie_list_returns_structure(self, browser):
        """list_cookies returns proper structure with count and cookies list."""
        tab = browser.main_tab

        from ai_dev_browser.core import list_cookies

        result = await list_cookies(tab)
        assert "cookies" in result
        assert "count" in result
        assert isinstance(result["cookies"], list)
        assert isinstance(result["count"], int)
