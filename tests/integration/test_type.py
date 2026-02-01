"""Integration tests for type_text functionality."""

import time

from ai_dev_browser.core import human, type_text


class TestTypeDefault:
    """Test default type behavior (native, no delays)."""

    async def test_type_text_works(self, test_page):
        """Basic typing should work."""
        await type_text(test_page, "hello", selector="#input1")

        value = await test_page.evaluate("document.getElementById('input1').value")
        assert value == "hello"

    async def test_type_is_fast_by_default(self, test_page):
        """Default typing should be fast (no delays)."""
        text = "quick brown fox"

        start = time.perf_counter()
        await type_text(test_page, text, selector="#input1")
        elapsed = time.perf_counter() - start

        # Should be very fast without humanization (< 100ms)
        assert elapsed < 0.5, f"Native typing took {elapsed:.2f}s, expected < 0.5s"


class TestTypeHumanized:
    """Test humanized typing with delays."""

    async def test_type_humanized_is_slower(self, test_page):
        """Humanized typing should have delays between keystrokes."""
        human.configure(type_humanize=True)
        text = "hello"  # 5 characters

        start = time.perf_counter()
        await type_text(test_page, text, selector="#input1")
        elapsed = time.perf_counter() - start

        # With 25-45ms delay per char, 5 chars should take ~125-225ms
        assert elapsed > 0.1, f"Humanized typing should take longer, took {elapsed:.2f}s"

        value = await test_page.evaluate("document.getElementById('input1').value")
        assert value == "hello"

    async def test_type_explicit_human_like_param(self, test_page):
        """human_like parameter should override config."""
        human.configure(type_humanize=False)  # Config says no

        text = "test"
        start = time.perf_counter()
        await type_text(test_page, text, selector="#input1", human_like=True)  # Param says yes
        elapsed = time.perf_counter() - start

        # Should use delays despite config
        assert elapsed > 0.05, "human_like=True should add delays"

    async def test_type_explicit_native_param(self, test_page):
        """human_like=False should be fast even if config says humanize."""
        human.configure(type_humanize=True)  # Config says yes

        text = "quick test"
        start = time.perf_counter()
        await type_text(test_page, text, selector="#input1", human_like=False)  # Param says no
        elapsed = time.perf_counter() - start

        # Should be fast despite config
        assert elapsed < 0.3, f"human_like=False should be fast, took {elapsed:.2f}s"


class TestTypeClear:
    """Test clear functionality."""

    async def test_type_with_clear(self, test_page):
        """clear=True should clear existing content first."""
        # Type initial content
        await type_text(test_page, "initial", selector="#input1")

        # Type new content with clear
        await type_text(test_page, "replaced", selector="#input1", clear=True)

        value = await test_page.evaluate("document.getElementById('input1').value")
        assert value == "replaced"

    async def test_type_without_clear_appends(self, test_page):
        """Without clear, typing appends to existing content."""
        await type_text(test_page, "hello", selector="#input1")
        await type_text(test_page, "world", selector="#input1")

        value = await test_page.evaluate("document.getElementById('input1').value")
        assert value == "helloworld"


class TestTypeSpecialCharacters:
    """Test typing special characters."""

    async def test_type_unicode(self, test_page):
        """Should handle unicode characters."""
        await type_text(test_page, "你好世界", selector="#input1")

        value = await test_page.evaluate("document.getElementById('input1').value")
        assert value == "你好世界"

    async def test_type_with_spaces(self, test_page):
        """Should handle spaces correctly."""
        await type_text(test_page, "hello world", selector="#input1")

        value = await test_page.evaluate("document.getElementById('input1').value")
        assert value == "hello world"

    async def test_type_numbers_and_symbols(self, test_page):
        """Should handle numbers and symbols."""
        await type_text(test_page, "test123!@#", selector="#input1")

        value = await test_page.evaluate("document.getElementById('input1').value")
        assert value == "test123!@#"
