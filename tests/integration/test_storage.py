"""Integration tests for storage and eval operations."""

import asyncio

from ai_dev_browser.core import goto


class TestPageEval:
    """Test JavaScript evaluation."""

    async def test_evaluate_returns_value(self, browser):
        """Should return evaluated value."""
        tab = browser.main_tab

        result = await tab.evaluate("1 + 2")
        assert result == 3

    async def test_evaluate_dom_access(self, test_page):
        """Should access DOM elements."""
        result = await test_page.evaluate("document.getElementById('btn1').tagName")
        assert result.upper() == "BUTTON"

    async def test_evaluate_complex_expression(self, browser):
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

        count = await tab.evaluate("document.querySelectorAll('#list li').length")
        assert count == 3

    async def test_evaluate_window_properties(self, browser):
        """Should access window properties."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html>
<body>
    <script>
        window.customData = { name: 'test', value: 42 };
    </script>
</body>
</html>"""

        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await goto(tab, data_url)
        await asyncio.sleep(0.2)

        name = await tab.evaluate("window.customData.name")
        value = await tab.evaluate("window.customData.value")
        assert name == "test"
        assert value == 42
