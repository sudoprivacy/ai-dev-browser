"""Integration tests for element operations."""

import asyncio

from ai_dev_browser.core import (
    find_by_xpath,
    find_element,
    find_element_info,
    find_elements,
    focus_element,
    get_element_text,
    goto,
    scroll,
    wait_for_element,
    wait_for_element_with_info,
)


class TestFindElement:
    """Test finding elements."""

    async def test_find_by_selector(self, test_page):
        """Should find element by CSS selector."""
        result = await find_element(test_page, selector="#btn1")
        assert result["found"] is True
        assert result["element"] is not None

    async def test_find_by_text(self, test_page):
        """Should find element by text content."""
        result = await find_element(test_page, text="Button 2")
        assert result["found"] is True
        assert result["element"] is not None

    async def test_find_returns_none_for_missing(self, test_page):
        """Should return found=False for non-existent element."""
        result = await find_element(test_page, selector="#nonexistent", timeout=1)
        assert result["found"] is False
        assert result["element"] is None


class TestFindElementInfo:
    """Test find_element_info which returns CLI-friendly info."""

    async def test_find_single_element_info(self, test_page):
        """Should return tag and text for single element."""
        result = await find_element_info(test_page, selector="#btn1")
        assert isinstance(result, dict)
        assert result["found"] is True
        assert result["tag"] == "button"
        assert "Button 1" in result["text"]

    async def test_find_all_elements_info(self, test_page):
        """Should return count for multiple elements."""
        result = await find_element_info(test_page, selector=".btn", all_elements=True)
        assert isinstance(result, dict)
        assert result["found"] is True
        assert result["count"] >= 2

    async def test_find_element_info_not_found(self, test_page):
        """Should return found=False for missing element."""
        result = await find_element_info(test_page, selector="#nonexistent", timeout=1)
        assert result["found"] is False


class TestFindElements:
    """Test finding multiple elements."""

    async def test_find_all_matching(self, test_page):
        """Should find all matching elements."""
        result = await find_elements(test_page, selector=".btn")
        assert result["count"] >= 2  # btn1 and btn2
        assert isinstance(result["elements"], list)


class TestFindByXpath:
    """Test XPath queries."""

    async def test_xpath_finds_element(self, test_page):
        """Should find element by XPath."""
        result = await find_by_xpath(test_page, "//button")
        assert result["count"] >= 2


class TestWaitForElement:
    """Test waiting for elements."""

    async def test_wait_for_existing_element(self, test_page):
        """Should return immediately for existing element."""
        result = await wait_for_element(test_page, selector="#btn1", timeout=5)
        assert result["found"] is True
        assert result["elapsed"] < 1.0

    async def test_wait_for_dynamic_element(self, browser):
        """Should wait for dynamically added element."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html>
<body>
    <div id="container"></div>
    <script>
        setTimeout(() => {
            const el = document.createElement('div');
            el.id = 'dynamic';
            el.innerText = 'Dynamic Content';
            document.getElementById('container').appendChild(el);
        }, 300);
    </script>
</body>
</html>"""

        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await goto(tab, data_url)

        result = await wait_for_element(tab, selector="#dynamic", timeout=5)
        assert result["found"] is True

    async def test_wait_timeout_for_missing(self, test_page):
        """Should timeout for non-existent element."""
        result = await wait_for_element(test_page, selector="#never-exists", timeout=1)
        assert result["found"] is False


class TestWaitForElementWithInfo:
    """Test wait_for_element_with_info which includes messages."""

    async def test_wait_with_message_found(self, test_page):
        """Should include success message when found."""
        result = await wait_for_element_with_info(test_page, text="Button 1", timeout=5)
        assert result["found"] is True
        assert "message" in result
        assert "found" in result["message"].lower()

    async def test_wait_with_message_timeout(self, test_page):
        """Should include timeout message."""
        result = await wait_for_element_with_info(test_page, selector="#never-exists", timeout=1)
        assert result["found"] is False
        assert "message" in result
        assert "timeout" in result["message"].lower()


class TestFocusElement:
    """Test focusing elements."""

    async def test_focus_by_selector(self, test_page):
        """Should focus element by selector."""
        result = await focus_element(test_page, selector="#input1")
        assert isinstance(result, dict)
        assert result["focused"] is True

    async def test_focus_not_found(self, test_page):
        """Should return focused=False for missing element."""
        result = await focus_element(test_page, selector="#nonexistent", timeout=1)
        assert result["focused"] is False
        assert "error" in result


class TestGetElementText:
    """Test getting element text content."""

    async def test_get_text_by_selector(self, test_page):
        """Should get text content."""
        result = await get_element_text(test_page, selector="#btn1")
        assert isinstance(result, dict)
        assert "text" in result
        assert "Button 1" in result["text"]

    async def test_get_text_not_found(self, test_page):
        """Should return error for missing element."""
        result = await get_element_text(test_page, selector="#nonexistent", timeout=1)
        assert result["text"] is None
        assert "error" in result


class TestScroll:
    """Test scroll operations."""

    async def test_scroll_down(self, browser):
        """Should scroll page down."""
        tab = browser.main_tab

        # Create tall page
        html = """<!DOCTYPE html>
<html>
<body style="height: 3000px;">
    <div id="top">Top</div>
    <div id="bottom" style="position: absolute; bottom: 0;">Bottom</div>
    <script>
        window.scrollPositions = [];
        window.addEventListener('scroll', () => {
            window.scrollPositions.push(window.scrollY);
        });
    </script>
</body>
</html>"""

        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await goto(tab, data_url)
        await asyncio.sleep(0.2)

        initial_scroll = await tab.evaluate("window.scrollY")
        assert initial_scroll == 0

        await scroll(tab, direction="down", amount=50)
        await asyncio.sleep(0.2)

        new_scroll = await tab.evaluate("window.scrollY")
        assert new_scroll > initial_scroll

    async def test_scroll_to_bottom(self, browser):
        """Should scroll to page bottom."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html>
<body style="height: 3000px;"></body>
</html>"""

        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await goto(tab, data_url)
        await asyncio.sleep(0.2)

        await scroll(tab, to_bottom=True)
        await asyncio.sleep(0.2)

        scroll_y = await tab.evaluate("window.scrollY")
        assert scroll_y > 1000  # Should be near bottom

    async def test_scroll_to_top(self, browser):
        """Should scroll to page top."""
        tab = browser.main_tab

        html = """<!DOCTYPE html>
<html>
<body style="height: 3000px;"></body>
</html>"""

        import base64

        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await goto(tab, data_url)
        await asyncio.sleep(0.2)

        # Scroll down first
        await tab.evaluate("window.scrollTo(0, 1000)")
        await asyncio.sleep(0.1)

        # Scroll to top
        await scroll(tab, to_top=True)
        await asyncio.sleep(0.2)

        scroll_y = await tab.evaluate("window.scrollY")
        assert scroll_y == 0
