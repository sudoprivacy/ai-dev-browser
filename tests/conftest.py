"""Pytest fixtures for integration tests."""

import contextlib
import os

import nodriver
import pytest
from ai_dev_browser.core import human


SKIP_BROWSER = os.environ.get("SKIP_BROWSER_TESTS", "").lower() in ("1", "true", "yes")


@pytest.fixture(scope="function")
async def browser():
    """Start a browser for testing."""
    if SKIP_BROWSER:
        pytest.skip("Browser tests skipped")

    browser = await nodriver.start(
        headless=True,
        browser_args=["--no-sandbox", "--disable-gpu"],
    )
    yield browser
    with contextlib.suppress(Exception):
        browser.stop()


@pytest.fixture(autouse=True)
def reset_human_config():
    """Reset human config to defaults before each test."""
    original = human.HumanConfig()
    yield
    human.configure(
        use_gaussian_path=original.use_gaussian_path,
        click_offset_enabled=original.click_offset_enabled,
        click_hold_enabled=original.click_hold_enabled,
        double_click_humanize=original.double_click_humanize,
        type_humanize=original.type_humanize,
        typo_enabled=original.typo_enabled,
    )
