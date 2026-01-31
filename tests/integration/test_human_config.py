"""Integration tests for human-like behavior configuration."""

import pytest

from ai_dev_browser.core import human


class TestHumanConfigDefaults:
    """Test default configuration values."""

    def test_default_click_offset_enabled(self):
        """Click offset should be enabled by default (FREE feature)."""
        config = human.get_config()
        assert config.click_offset_enabled is True

    def test_default_gaussian_path_disabled(self):
        """Gaussian path should be disabled by default (has cost)."""
        config = human.get_config()
        assert config.use_gaussian_path is False

    def test_default_click_hold_disabled(self):
        """Click hold should be disabled by default (has cost)."""
        config = human.get_config()
        assert config.click_hold_enabled is False

    def test_default_type_humanize_disabled(self):
        """Type humanize should be disabled by default (has cost)."""
        config = human.get_config()
        assert config.type_humanize is False

    def test_default_double_click_humanize_disabled(self):
        """Double click humanize should be disabled by default."""
        config = human.get_config()
        assert config.double_click_humanize is False


class TestHumanConfigure:
    """Test human.configure() function."""

    def test_configure_single_option(self):
        """Should configure a single option."""
        human.configure(use_gaussian_path=True)

        config = human.get_config()
        assert config.use_gaussian_path is True

    def test_configure_multiple_options(self):
        """Should configure multiple options at once."""
        human.configure(
            use_gaussian_path=True,
            click_hold_enabled=True,
            type_humanize=True,
        )

        config = human.get_config()
        assert config.use_gaussian_path is True
        assert config.click_hold_enabled is True
        assert config.type_humanize is True

    def test_configure_returns_config(self):
        """Configure should return the config object."""
        result = human.configure(click_offset_enabled=False)

        assert isinstance(result, human.HumanConfig)
        assert result.click_offset_enabled is False

    def test_configure_ignores_unknown_keys(self):
        """Unknown keys should be ignored without error."""
        # Should not raise
        human.configure(unknown_key=True, another_unknown=123)

        # Config should remain unchanged for known keys
        config = human.get_config()
        assert hasattr(config, "click_offset_enabled")


class TestHumanConfigValues:
    """Test specific config values."""

    def test_click_timing_values(self):
        """Click timing should use pro gamer values."""
        config = human.get_config()

        # 30-60ms for pro gamer level
        assert config.click_hold_min_ms == 30
        assert config.click_hold_max_ms == 60

    def test_double_click_timing_values(self):
        """Double click interval should be fast but human."""
        config = human.get_config()

        # 40-80ms
        assert config.double_click_interval_min_ms == 40
        assert config.double_click_interval_max_ms == 80

    def test_typing_speed_values(self):
        """Typing speed should be competitive programmer level."""
        config = human.get_config()

        # 25-45ms for ~300-400 WPM
        assert config.type_delay_min_ms == 25
        assert config.type_delay_max_ms == 45

    def test_click_offset_ratio(self):
        """Click offset ratio should be ±20%."""
        config = human.get_config()
        assert config.click_offset_ratio == 0.2


class TestMousePositionTracking:
    """Test mouse position tracking (no browser needed for basic tests)."""

    def test_set_and_get_pos_with_mock(self):
        """Should store and retrieve position using mock tab."""
        # Mock tab with target.target_id
        class MockTarget:
            target_id = "test-tab-1"

        class MockTab:
            target = MockTarget()

        tab = MockTab()
        human.set_last_mouse_pos(tab, 123, 456)

        pos = human.get_last_mouse_pos(tab)
        assert pos == (123, 456)

    def test_default_pos_for_new_tab(self):
        """New tabs should have default (0, 0) position."""
        class MockTarget:
            target_id = "new-tab-id"

        class MockTab:
            target = MockTarget()

        tab = MockTab()
        pos = human.get_last_mouse_pos(tab)
        assert pos == (0, 0)

    def test_positions_are_per_tab(self):
        """Each tab should have its own position."""
        class MockTarget1:
            target_id = "tab-1"

        class MockTarget2:
            target_id = "tab-2"

        class MockTab1:
            target = MockTarget1()

        class MockTab2:
            target = MockTarget2()

        tab1 = MockTab1()
        tab2 = MockTab2()

        human.set_last_mouse_pos(tab1, 100, 100)
        human.set_last_mouse_pos(tab2, 200, 200)

        assert human.get_last_mouse_pos(tab1) == (100, 100)
        assert human.get_last_mouse_pos(tab2) == (200, 200)


class TestGaussianPathGeneration:
    """Test Gaussian path generation."""

    def test_generate_path_returns_points(self):
        """Path generation should return list of points."""
        path = human.generate_gaussian_path(0, 0, 100, 100, duration=0.1)

        assert isinstance(path, list)
        assert len(path) > 0
        assert all(isinstance(p, tuple) and len(p) == 2 for p in path)

    def test_generate_path_starts_at_start(self):
        """Path should start at the start point."""
        path = human.generate_gaussian_path(50, 50, 200, 200)

        assert path[0] == (50, 50)

    def test_generate_path_ends_at_end(self):
        """Path should end at the end point."""
        path = human.generate_gaussian_path(50, 50, 200, 200)

        assert path[-1] == (200, 200)

    def test_generate_path_has_multiple_points(self):
        """Path should have multiple points for smooth movement."""
        path = human.generate_gaussian_path(0, 0, 500, 500, duration=0.3)

        # At 60fps, 0.3s should give ~18 points
        assert len(path) >= 6


class TestCalculateClickOffset:
    """Test click offset calculation."""

    def test_offset_within_bounds(self):
        """Offset should be within ±ratio of dimensions."""
        width, height = 100, 50

        for _ in range(100):
            offset_x, offset_y = human.calculate_click_offset(width, height, ratio=0.2)

            assert -20 <= offset_x <= 20, f"offset_x {offset_x} out of bounds"
            assert -10 <= offset_y <= 10, f"offset_y {offset_y} out of bounds"

    def test_offset_varies(self):
        """Offset should vary (not always the same)."""
        offsets = [human.calculate_click_offset(100, 100) for _ in range(20)]

        unique_offsets = set(offsets)
        assert len(unique_offsets) > 1, "Offsets should vary"
