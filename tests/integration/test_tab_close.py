"""tab_close actually closes the browser tab and reports an honest count (E2E).

The bug: tab_close only disconnected adb's per-tab WebSocket (the tab stayed
open) and returned len(browser.tabs) computed from a stale target list — so a
no-op close returned a plausible {remaining} with no error. It now drives
Target.closeTarget, re-fetches targets, and verifies the close. Launches a real
headless Chrome (CDP transport).
"""

from __future__ import annotations

import contextlib

import pytest

from ai_dev_browser.core import connect_browser, get_active_tab
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.tabs import tab_close, tab_list, tab_new


@pytest.fixture
async def browser():
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, result
    port = result["port"]
    b = None
    try:
        b = await connect_browser(port=port)
        await get_active_tab(b)
        yield b
    finally:
        if b is not None:
            with contextlib.suppress(Exception):
                await b.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


@pytest.mark.asyncio
async def test_tab_close_actually_closes_and_count_is_live(browser):
    await tab_new(browser, url="https://example.com")
    await tab_new(browser, url="https://example.org")
    before = (await tab_list(browser))["count"]
    assert before >= 3

    res = await tab_close(browser, tab_id=1)
    assert res["closed"] is True, res
    assert res["remaining"] == before - 1, res  # live count, not the pre-close one

    after = (await tab_list(browser))["count"]
    assert after == before - 1, (before, after)  # the tab is really gone


@pytest.mark.asyncio
async def test_tab_close_refuses_last_tab(browser):
    with pytest.raises(ValueError, match="last tab"):
        await tab_close(browser, tab_id=0)
