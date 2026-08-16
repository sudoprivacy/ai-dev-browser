"""`click_by_xpath` / `click_by_html_id` scroll the target into view and fire a
TRUSTED CDP mouse click — not a synthetic `el.click()`.

Reported on a government SPA: the download links had no accessible name (so
`click_by_text` couldn't match), and `click_by_xpath` located them but didn't
trigger the download — because it dispatched `el.click()`, which is
`isTrusted=false`, and the site gates on trusted events. Worse, once the page
scrolled the link off-screen, raw-coordinate `mouse_click` missed entirely.

The fixture puts the target far below the fold and records `event.isTrusted`,
so both properties are pinned: the click lands (scrolled into view) AND it's a
real trusted event.
"""

from __future__ import annotations

import base64
import contextlib
import os

import pytest

from ai_dev_browser.core import (
    click_by_html_id,
    click_by_xpath,
    js_evaluate,
    page_goto,
)
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, get_active_tab

SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)

# Target is 3000px down — well below the default ~950px viewport, so a click can
# only land if the tool scrolls first. The handler records e.isTrusted, so a
# synthetic el.click() (isTrusted=false) would be caught.
_FIXTURE = (
    "<!doctype html><meta charset=utf-8><body>"
    "<div style='height:3000px'>spacer</div>"
    "<button id=dl data-role=download>下载</button>"  # no accessible name
    "<script>window.__trusted=null;"
    "document.getElementById('dl').addEventListener('click',"
    "function(e){window.__trusted=e.isTrusted;});</script></body>"
)
_URL = "data:text/html;base64," + base64.b64encode(_FIXTURE.encode()).decode()


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


@pytest.fixture
async def tab():
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    browser = None
    try:
        browser = await connect_browser(port=port)
        the_tab = await get_active_tab(browser)
        await page_goto(the_tab, _URL)
        yield the_tab
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        browser_stop(port=port)


async def _reset(tab):
    await js_evaluate(tab, "window.__trusted=null; scrollTo(0,0)")


async def _trusted(tab):
    return (await js_evaluate(tab, "window.__trusted"))["result"]


async def test_click_by_html_id_scrolls_and_fires_trusted(tab):
    result = await click_by_html_id(tab, "dl")
    assert result["clicked"] is True, result
    assert result.get("scrolled_into_view") is True, (
        f"target was below the fold; the tool should report the scroll: {result}"
    )
    assert await _trusted(tab) is True, "click must be a trusted event, not el.click()"


async def test_click_by_xpath_scrolls_and_fires_trusted(tab):
    """The reporter's exact locator: an XPath for a no-accessible-name control."""
    await _reset(tab)
    result = await click_by_xpath(tab, "//button[@data-role='download']")
    assert result["clicked"] is True, result
    assert result.get("scrolled_into_view") is True, result
    assert await _trusted(tab) is True, "xpath click must be trusted"


async def test_click_by_xpath_no_match_reports_not_clicked(tab):
    """A miss is a clean {clicked: False}, not an exception."""
    result = await click_by_xpath(tab, "//button[@id='does-not-exist']")
    assert result["clicked"] is False, result
    assert result.get("navigated") is False
