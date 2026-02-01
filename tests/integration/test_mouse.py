"""Integration tests for mouse operations."""

import time

from ai_dev_browser.core import human, mouse_click, mouse_move

from tests.conftest import eval_json


class TestMouseMove:
    """Test mouse movement functionality."""

    async def test_mouse_move_updates_position(self, test_page):
        """Mouse move should update cursor position."""
        await mouse_move(test_page, 100, 200)

        last_move = await eval_json(test_page, "window.lastMouseMove")
        assert last_move is not None
        assert abs(last_move["x"] - 100) <= 5
        assert abs(last_move["y"] - 200) <= 5

    async def test_mouse_position_tracking(self, test_page):
        """Mouse position should be tracked per tab."""
        await mouse_move(test_page, 150, 250)

        pos = human.get_last_mouse_pos(test_page)
        assert pos == (150, 250)

    async def test_mouse_move_native_is_fast(self, test_page):
        """Native (linear) mouse move should be fast."""
        human.configure(use_gaussian_path=False)

        start = time.perf_counter()
        for _ in range(5):
            await mouse_move(test_page, 100, 100)
            await mouse_move(test_page, 500, 300)
        elapsed = time.perf_counter() - start

        # 10 moves should be fast (< 5s, allowing for system variance)
        assert elapsed < 5.0, f"Native moves took {elapsed:.2f}s"

    async def test_mouse_move_gaussian_has_delay(self, test_page):
        """Gaussian mouse move should take longer due to path simulation."""
        human.configure(use_gaussian_path=True, mouse_duration=0.1)

        start = time.perf_counter()
        await mouse_move(test_page, 500, 300)
        elapsed = time.perf_counter() - start

        # With 0.1s duration, should take ~100ms
        assert elapsed > 0.05, f"Gaussian move should take time, took {elapsed:.2f}s"


class TestMouseClick:
    """Test mouse click at coordinates."""

    async def test_mouse_click_at_coordinates(self, test_page):
        """Click at specific coordinates."""
        # Get button position
        btn_pos = await eval_json(
            test_page,
            """
            (() => {
                const btn = document.getElementById('btn1');
                const rect = btn.getBoundingClientRect();
                return { x: rect.x + rect.width/2, y: rect.y + rect.height/2 };
            })()
        """,
        )

        await mouse_click(test_page, btn_pos["x"], btn_pos["y"])

        clicks = await eval_json(test_page, "window.clicks")
        assert "btn1" in clicks

    async def test_mouse_click_triggers_trusted_event(self, test_page):
        """Mouse click should produce trusted events."""
        btn_pos = await eval_json(
            test_page,
            """
            (() => {
                const btn = document.getElementById('btn1');
                const rect = btn.getBoundingClientRect();
                return { x: rect.x + rect.width/2, y: rect.y + rect.height/2 };
            })()
        """,
        )

        await mouse_click(test_page, btn_pos["x"], btn_pos["y"])

        event = await eval_json(test_page, "window.lastEvent")
        assert event["isTrusted"] is True

    async def test_mouse_double_click(self, test_page):
        """Double click should work."""
        btn_pos = await eval_json(
            test_page,
            """
            (() => {
                const btn = document.getElementById('btn1');
                const rect = btn.getBoundingClientRect();
                return { x: rect.x + rect.width/2, y: rect.y + rect.height/2 };
            })()
        """,
        )

        await human.mouse_double_click(test_page, btn_pos["x"], btn_pos["y"])

        clicks = await eval_json(test_page, "window.clicks")
        # Double click triggers onclick twice
        assert clicks.count("btn1") >= 1


class TestMousePositionContinuity:
    """Test that mouse position is tracked across moves."""

    async def test_consecutive_moves_use_last_position(self, test_page):
        """Second move should start from first move's end position."""
        # First move
        await mouse_move(test_page, 100, 100)
        pos1 = human.get_last_mouse_pos(test_page)
        assert pos1 == (100, 100)

        # Second move (should start from 100,100)
        await mouse_move(test_page, 200, 200)
        pos2 = human.get_last_mouse_pos(test_page)
        assert pos2 == (200, 200)

    async def test_new_tab_starts_at_origin(self, browser):
        """New tab should have mouse at (0,0)."""
        new_tab = await browser.get("about:blank")

        pos = human.get_last_mouse_pos(new_tab)
        assert pos == (0, 0)


class TestMouseHoldTime:
    """Test click hold time configuration."""

    async def test_click_with_hold_time(self, test_page):
        """With hold enabled, click should be slightly slower."""
        human.configure(click_hold_enabled=True)

        btn_pos = await eval_json(
            test_page,
            """
            (() => {
                const btn = document.getElementById('btn1');
                const rect = btn.getBoundingClientRect();
                return { x: rect.x + rect.width/2, y: rect.y + rect.height/2 };
            })()
        """,
        )

        start = time.perf_counter()
        await mouse_click(test_page, btn_pos["x"], btn_pos["y"])
        elapsed = time.perf_counter() - start

        # With 30-60ms hold, click should take at least 30ms
        assert elapsed > 0.02, f"Click with hold should take longer, took {elapsed:.2f}s"

    async def test_click_without_hold_time(self, test_page):
        """Without hold, click should be instant."""
        human.configure(click_hold_enabled=False)

        btn_pos = await eval_json(
            test_page,
            """
            (() => {
                const btn = document.getElementById('btn1');
                const rect = btn.getBoundingClientRect();
                return { x: rect.x + rect.width/2, y: rect.y + rect.height/2 };
            })()
        """,
        )

        start = time.perf_counter()
        for _ in range(5):
            await mouse_click(test_page, btn_pos["x"], btn_pos["y"])
        elapsed = time.perf_counter() - start

        # 5 clicks without hold should be fast (< 3s, allowing for system variance)
        assert elapsed < 3.0, f"Clicks without hold should be fast, took {elapsed:.2f}s"
