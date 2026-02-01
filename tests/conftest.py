"""Pytest fixtures for integration tests."""

import asyncio
import contextlib
import json

# Skip browser tests if SKIP_BROWSER_TESTS env var is set
import os

import nodriver
import pytest
from ai_dev_browser.core import human


SKIP_BROWSER = os.environ.get("SKIP_BROWSER_TESTS", "").lower() in ("1", "true", "yes")


async def eval_json(tab, js_expr):
    """Evaluate JS and return parsed JSON result."""
    result = await tab.evaluate(f"JSON.stringify({js_expr})")
    if result is None or result == "null":
        return None
    return json.loads(result)


@pytest.fixture(scope="function")
async def browser():
    """Start a browser for testing.

    Creates a new browser for each test function.
    This is slower but more reliable than session-scoped.
    """
    if SKIP_BROWSER:
        pytest.skip("Browser tests skipped")

    browser = await nodriver.start(
        headless=True,
        browser_args=["--no-sandbox", "--disable-gpu"],
    )
    yield browser
    with contextlib.suppress(Exception):
        browser.stop()


@pytest.fixture
async def tab(browser):
    """Get the main tab from browser."""
    yield browser.main_tab


@pytest.fixture
async def test_page(browser):
    """Load a test page with clickable elements."""
    tab = browser.main_tab

    # Navigate to a data URL with our test page
    html = """<!DOCTYPE html>
<html>
<head>
    <style>
        .btn { padding: 20px 40px; margin: 10px; cursor: pointer; }
        #click-log { margin-top: 20px; }
    </style>
</head>
<body>
    <button id="btn1" class="btn" onclick="logClick('btn1')">Button 1</button>
    <button id="btn2" class="btn" onclick="logClick('btn2')">Button 2</button>
    <input id="input1" type="text" placeholder="Type here">
    <div id="click-log"></div>
    <script>
        window.clicks = [];
        window.lastEvent = null;
        function logClick(id) {
            window.clicks.push(id);
            document.getElementById('click-log').innerText = 'Clicked: ' + window.clicks.join(', ');
        }
        document.addEventListener('click', function(e) {
            window.lastEvent = {
                isTrusted: e.isTrusted,
                x: e.clientX,
                y: e.clientY,
                target: e.target.id
            };
        });
        document.addEventListener('mousemove', function(e) {
            window.lastMouseMove = { x: e.clientX, y: e.clientY };
        });
    </script>
</body>
</html>"""

    import base64

    data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
    await tab.get(data_url)
    await asyncio.sleep(0.3)  # Let page render
    yield tab


@pytest.fixture(autouse=True)
def reset_human_config():
    """Reset human config to defaults before each test."""
    # Store original values
    original = human.HumanConfig()

    yield

    # Reset to defaults after test
    human.configure(
        use_gaussian_path=original.use_gaussian_path,
        click_offset_enabled=original.click_offset_enabled,
        click_hold_enabled=original.click_hold_enabled,
        double_click_humanize=original.double_click_humanize,
        type_humanize=original.type_humanize,
        typo_enabled=original.typo_enabled,
    )
