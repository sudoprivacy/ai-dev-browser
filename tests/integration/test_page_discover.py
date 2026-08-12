"""Regression: page_discover must survive numeric accessibility values.

Reported on Kingdee Cloud Star (金蝶云星空): page_discover threw
`{"error": "'int' object is not subscriptable"}` and returned NO refs, forcing
the agent to eyeball `mouse_click --x --y` (and mis-click adjacent controls).

Root cause: a slider / spinbutton / progress node reports a NUMERIC
accessibility `value` (and occasionally `name`). `snapshot._format_ax_node`
sliced it (`val[:50]`) without coercing to str, so the TypeError aborted the
WHOLE `Accessibility.getFullAXTree` walk — one numeric input anywhere on the
page took out the entire snapshot. ARIA-poor enterprise pages are full of them.

The fix coerces to str before slicing. These tests pin: (1) no crash, and
(2) the numeric value survives as a string field.
"""

from __future__ import annotations

import base64
import contextlib
import os

import pytest

from ai_dev_browser.core import page_discover, page_goto
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, get_active_tab

SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


# Range / spinbutton / progress all surface a numeric AX value — the shape that
# crashed the snapshot. A plain button is here too so a healthy snapshot has
# something unambiguous to find.
_FIXTURE = """<!DOCTYPE html><html><body>
<input type="range" min="0" max="100" value="42" aria-label="volume">
<div role="spinbutton" aria-valuenow="7" tabindex="0">quantity</div>
<progress value="70" max="100"></progress>
<button>Confirm</button>
</body></html>"""


@pytest.fixture
async def tab():
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    browser_client = None
    try:
        browser_client = await connect_browser(port=port)
        the_tab = await get_active_tab(browser_client)
        url = "data:text/html;base64," + base64.b64encode(_FIXTURE.encode()).decode()
        await page_goto(the_tab, url)
        yield the_tab
    finally:
        if browser_client is not None:
            with contextlib.suppress(Exception):
                await browser_client.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


async def test_page_discover_survives_numeric_ax_values(tab):
    """The crash pin: a page with numeric-valued controls must NOT abort the
    snapshot — page_discover returns a real list, not an error."""
    elements = await page_discover(tab, interactable_only=False)
    assert isinstance(elements, list), (
        f"page_discover did not return a list: {elements}"
    )
    assert elements, "snapshot came back empty — the numeric-value crash is back"

    # The button proves the walk completed past the numeric nodes.
    names = [e.get("name") for e in elements]
    assert "Confirm" in names, f"walk aborted before the button; got {names}"


async def test_page_discover_numeric_value_is_stringified(tab):
    """The numeric slider value must survive as a string field (not dropped,
    not left as an int the JSON/consumers would treat inconsistently)."""
    elements = await page_discover(tab, interactable_only=False)
    slider = next((e for e in elements if e.get("role") == "slider"), None)
    assert slider is not None, f"slider missing from snapshot: {elements}"
    assert slider.get("value") == "42", f"slider value wrong: {slider}"
    assert isinstance(slider["value"], str), "value must be coerced to str"
