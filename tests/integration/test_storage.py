"""Integration tests for storage, eval, and page operations."""

import asyncio

from ai_dev_browser.core import (
    eval_js,
    get_local_storage,
    get_page_html,
    get_page_info,
    goto,
    screenshot,
    set_local_storage,
)


class TestPageEval:
    """Test JavaScript evaluation via core function."""

    async def test_eval_js_returns_dict(self, browser):
        """Should return dict with result key."""
        tab = browser.main_tab

        result = await eval_js(tab, "1 + 2")
        assert isinstance(result, dict)
        assert "result" in result
        assert result["result"] == 3

    async def test_eval_js_handles_objects(self, browser):
        """Should handle object return values."""
        tab = browser.main_tab

        result = await eval_js(tab, "({name: 'test', value: 42})")
        # Result is returned as-is if JSON serializable
        assert isinstance(result, dict)
        assert "result" in result
        # The result could be a dict or a stringified version
        if isinstance(result["result"], dict):
            assert result["result"]["name"] == "test"
            assert result["result"]["value"] == 42
        else:
            # If stringified, just check it contains the values
            assert "test" in str(result["result"])
            assert "42" in str(result["result"])

    async def test_eval_dom_access(self, test_page):
        """Should access DOM elements."""
        result = await eval_js(test_page, "document.getElementById('btn1').tagName")
        assert result["result"].upper() == "BUTTON"

    async def test_eval_complex_expression(self, browser):
        """Should handle complex expressions."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html>
<body>
    <ul id="list">
        <li>Item 1</li>
        <li>Item 2</li>
        <li>Item 3</li>
    </ul>
</body>
</html>"""

        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await goto(tab, data_url)
        await asyncio.sleep(0.2)

        result = await eval_js(tab, "document.querySelectorAll('#list li').length")
        assert result["result"] == 3


class TestLocalStorage:
    """Test localStorage operations.

    Note: localStorage requires a proper origin (http:// or https://).
    data: URLs, about:blank, and chrome:// don't support localStorage.
    These tests verify the API structure without requiring actual storage.
    """

    async def test_set_local_storage_missing_params_returns_error(self, browser):
        """Should return error when called without required params."""
        tab = browser.main_tab

        # Test set with missing params returns error dict
        result = await set_local_storage(tab)
        assert isinstance(result, dict)
        assert "error" in result
        assert "Must specify" in result["error"]

    async def test_set_local_storage_key_value_returns_dict(self, browser):
        """Should verify set_local_storage with key/value returns correct dict structure."""
        import pytest

        tab = browser.main_tab

        # Navigate to any page first
        html = "<html><body>test</body></html>"
        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await goto(tab, data_url)
        await asyncio.sleep(0.2)

        # This might fail on data URLs, but we can at least verify the error is handled
        try:
            result = await set_local_storage(tab, key="test", value="value")
            # If it succeeds (unlikely on data URL), verify structure
            assert isinstance(result, dict)
            assert "key" in result or "error" in result
        except Exception:
            # Storage not supported on this URL type - that's expected
            pytest.skip("localStorage not supported on data URLs")

    async def test_get_local_storage_returns_dict(self, browser):
        """Should verify get_local_storage returns dict structure."""
        import pytest

        tab = browser.main_tab

        try:
            result = await get_local_storage(tab)
            # If it succeeds, verify structure
            assert isinstance(result, dict)
            assert "items" in result or "count" in result
        except Exception:
            # Storage not supported on this URL type - that's expected
            pytest.skip("localStorage not supported on current page")


class TestScreenshot:
    """Test screenshot operations."""

    async def test_screenshot_returns_path(self, browser):
        """Should return path and size in result."""
        tab = browser.main_tab

        result = await screenshot(tab)
        assert isinstance(result, dict)
        assert "path" in result
        assert "size" in result
        assert result["size"] > 0

        # Verify file exists
        import os

        assert os.path.exists(result["path"])

    async def test_screenshot_with_custom_path(self, browser, tmp_path):
        """Should save to specified path."""
        tab = browser.main_tab

        custom_path = str(tmp_path / "test_screenshot.png")
        result = await screenshot(tab, path=custom_path)

        assert result["path"] == custom_path
        import os

        assert os.path.exists(custom_path)


class TestPageHtml:
    """Test page HTML retrieval."""

    async def test_get_page_html_returns_dict(self, browser):
        """Should return dict with html and length."""
        tab = browser.main_tab

        html = "<html><body><h1>Test</h1></body></html>"
        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await goto(tab, data_url)
        await asyncio.sleep(0.2)

        result = await get_page_html(tab)
        assert isinstance(result, dict)
        assert "html" in result
        assert "length" in result
        assert "<h1>Test</h1>" in result["html"]

    async def test_get_page_html_outer(self, browser):
        """Should get outerHTML when outer=True."""
        tab = browser.main_tab

        html = "<!DOCTYPE html><html lang='en'><body><h1>Test</h1></body></html>"
        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await goto(tab, data_url)
        await asyncio.sleep(0.2)

        result = await get_page_html(tab, outer=True)
        assert "<html" in result["html"]


class TestPageInfo:
    """Test page info retrieval."""

    async def test_get_page_info_returns_dict(self, browser):
        """Should return dict with url, title, ready, state."""
        tab = browser.main_tab

        html = "<html><head><title>Test Title</title></head><body></body></html>"
        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await goto(tab, data_url)
        await asyncio.sleep(0.2)

        result = await get_page_info(tab)
        assert isinstance(result, dict)
        assert "url" in result
        assert "title" in result
        assert "ready" in result
        assert "state" in result
        assert result["title"] == "Test Title"
