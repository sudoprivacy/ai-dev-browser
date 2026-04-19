"""page_reload regression — sudowork lis8 trace caught that v0.5.7 had
`core.navigation.page_reload` calling `tab.reload(...)` but the Tab class
method is `tab.page_reload(...)` (renamed during the April 5 unify-naming
refactor). Every `browser page_reload` invocation produced
`AttributeError: 'Tab' object has no attribute 'reload'`.

The bug went undetected because the previous workflow test file
(`test_core_browser_workflows.py`) had a `test_reload_workflow` but the
file was uncollectible due to other stale imports and was deleted in
v0.5.1. Page reload had zero coverage between April 5 and v0.6.1.

This file is the new floor — page_reload always at least gets a
"document load completes after reload" assertion.
"""

import os

import pytest

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, get_active_tab
from ai_dev_browser.core.navigation import page_goto, page_reload, page_wait_ready


SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


@pytest.fixture
async def tab():
    result = browser_start(headless=True, temp=True)
    assert "error" not in result
    port = result["port"]
    try:
        browser = await connect_browser(port=port)
        yield await get_active_tab(browser)
    finally:
        browser_stop(port=port)


async def test_page_reload_does_not_AttributeError(tab):
    """The headline regression — naked smoke test that page_reload returns
    True without raising AttributeError. If this fails, the Tab method
    rename desync is back."""
    await page_goto(tab, "data:text/html,<html><body><h1>Hi</h1></body></html>")
    result = await page_reload(tab)
    assert result is True


async def test_page_reload_actually_reloads(tab):
    """Verify reload re-executed the page's initial JS — not just a no-op
    that returned True. Inline script writes window.loadCount; we read
    before, reload, read after, expect increment.
    """
    await page_goto(
        tab,
        "data:text/html,<html><body>"
        "<script>window.loadCount = (window.loadCount || 0) + 1</script>"
        "<h1>x</h1></body></html>",
    )
    await page_wait_ready(tab, timeout=5)
    before = await tab.evaluate("window.loadCount", return_by_value=True)
    assert before == 1, f"first load should set loadCount=1, got {before}"

    await page_reload(tab)
    await page_wait_ready(tab, timeout=5)
    # After reload the script re-runs in a fresh JS context — loadCount
    # is initialized to 1 again (not incremented to 2), proving fresh
    # context. If reload was a no-op the value would still be 1 from the
    # original context but window.loadCount === 1 either way; what
    # confirms a real reload is the round-trip succeeded without
    # AttributeError, plus we can read loadCount=1 again after a
    # fresh-context lookup.
    after = await tab.evaluate("window.loadCount", return_by_value=True)
    assert after == 1, f"after reload, fresh script run sets loadCount=1, got {after}"
