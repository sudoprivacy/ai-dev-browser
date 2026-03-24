"""Pytest fixtures for integration tests."""

import contextlib
import os

import pytest
from ai_dev_browser.core import human
from ai_dev_browser.core.browser import start_browser, stop_browser
from ai_dev_browser.core.connection import connect_browser


SKIP_BROWSER = os.environ.get("SKIP_BROWSER_TESTS", "").lower() in ("1", "true", "yes")


@pytest.fixture(scope="function")
async def browser():
    """Start a browser for testing."""
    if SKIP_BROWSER:
        pytest.skip("Browser tests skipped")

    result = start_browser(headless=True, temp=True)
    port = result["port"]
    browser_client = await connect_browser(port=port)
    yield browser_client
    with contextlib.suppress(Exception):
        stop_browser(port=port)


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
