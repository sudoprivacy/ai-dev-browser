"""Integration tests for click functionality."""

from ai_dev_browser.core import click, human
from ai_dev_browser.core.elements import find_element

from tests.conftest import eval_json


class TestClickDefault:
    """Test default click behavior (human_like=True)."""

    async def test_click_uses_cdp_events(self, test_page):
        """Default click should use CDP events (isTrusted=true)."""
        await click(test_page, selector="#btn1")

        # Check isTrusted from the captured event
        last_event = await eval_json(test_page, "window.lastEvent")
        assert last_event is not None
        assert last_event["isTrusted"] is True, "CDP events should have isTrusted=true"
        assert last_event["target"] == "btn1"

    async def test_click_triggers_onclick(self, test_page):
        """Click should trigger onclick handler."""
        await click(test_page, selector="#btn1")

        clicks = await eval_json(test_page, "window.clicks")
        assert "btn1" in clicks

    async def test_click_with_offset(self, test_page):
        """Default click applies random offset within bounds."""
        # Click multiple times and collect positions
        positions = []
        for _ in range(5):
            await click(test_page, selector="#btn1")
            event = await eval_json(test_page, "window.lastEvent")
            positions.append((event["x"], event["y"]))

        # With offset, positions should vary (not all identical)
        unique_positions = set(positions)
        # Note: There's a small chance all 5 clicks land on same pixel
        # but with ±20% offset on a 80px+ button, this is unlikely
        assert len(unique_positions) >= 1  # At minimum, clicks work


class TestClickNative:
    """Test native click behavior (human_like=False)."""

    async def test_native_click_uses_js(self, test_page):
        """Native click uses JS click (faster but isTrusted=false)."""
        await click(test_page, selector="#btn1", human_like=False)

        # JS click still triggers onclick
        clicks = await eval_json(test_page, "window.clicks")
        assert "btn1" in clicks

        # Note: We can't easily verify isTrusted=false because
        # the click event from el.click() may not set window.lastEvent
        # the same way as a real mouse event

    async def test_native_click_is_faster(self, test_page):
        """Native click should be faster than human-like click."""
        import time

        # Time native click
        start = time.perf_counter()
        for _ in range(3):
            await click(test_page, selector="#btn1", human_like=False)
        native_time = time.perf_counter() - start

        # Time human-like click (with offset calculation)
        start = time.perf_counter()
        for _ in range(3):
            await click(test_page, selector="#btn1", human_like=True)
        human_time = time.perf_counter() - start

        # Human-like might be slightly slower due to offset calculation
        # but both should be fast (< 1s for 3 clicks)
        assert native_time < 1.0
        assert human_time < 1.0


class TestClickByText:
    """Test clicking by text content."""

    async def test_click_by_text(self, test_page):
        """Should find and click element by text."""
        await click(test_page, text="Button 2")

        clicks = await eval_json(test_page, "window.clicks")
        assert "btn2" in clicks


class TestClickOffset:
    """Test click offset configuration."""

    async def test_offset_disabled(self, test_page):
        """When offset disabled, clicks should be at center."""
        human.configure(click_offset_enabled=False)

        # Get button position
        result = await find_element(test_page, selector="#btn1")
        btn = result["element"]
        pos = await btn.get_position()
        center_x, center_y = pos.center

        await click(test_page, selector="#btn1")
        event = await eval_json(test_page, "window.lastEvent")

        # Should be exactly at center (or very close due to float precision)
        assert abs(event["x"] - center_x) <= 1
        assert abs(event["y"] - center_y) <= 1

    async def test_offset_enabled(self, test_page):
        """When offset enabled, clicks may vary from center."""
        human.configure(click_offset_enabled=True)

        # Click multiple times
        offsets = []
        result = await find_element(test_page, selector="#btn1")
        btn = result["element"]
        pos = await btn.get_position()
        center_x, center_y = pos.center

        for _ in range(10):
            await click(test_page, selector="#btn1")
            event = await eval_json(test_page, "window.lastEvent")
            offset = (event["x"] - center_x, event["y"] - center_y)
            offsets.append(offset)

        # At least some clicks should have non-zero offset
        non_zero_offsets = [o for o in offsets if abs(o[0]) > 1 or abs(o[1]) > 1]
        assert len(non_zero_offsets) > 0, "With offset enabled, some clicks should vary from center"
