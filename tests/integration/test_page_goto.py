"""page_goto returns the URL that actually landed, not the pre-nav snapshot.

The bug this guards: page_goto read `title` live (post-nav) but `url` from
`tab.target.url`, the attach-time snapshot — still about:blank right after a
fresh navigation. So the result paired a post-nav title with a pre-nav URL.
Now both come from the same liveness (location.href / document.title).
Launches a real headless Chrome (E2E).
"""

from __future__ import annotations

import base64
import contextlib

import pytest

from ai_dev_browser.core import connect_browser, get_active_tab
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.navigation import page_goto


@pytest.fixture
async def tab():
    result = browser_start(headless=True, temp=True, reuse="none")  # opens about:blank
    assert "error" not in result, result
    port = result["port"]
    browser = None
    try:
        browser = await connect_browser(port=port)
        yield await get_active_tab(browser)
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


@pytest.mark.asyncio
async def test_page_goto_returns_post_nav_url(tab):
    html = "<!doctype html><title>Landed</title><body>ok</body>"
    url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
    res = await page_goto(tab, url)
    assert res.get("success") is True, res
    # The whole bug: url must be the page we navigated to, not the about:blank
    # the tab was attached at.
    assert res.get("url") == url, res
    assert "about:blank" not in res.get("url", ""), res
    # title and url now share liveness — both reflect the landed page.
    assert res.get("title") == "Landed", res
