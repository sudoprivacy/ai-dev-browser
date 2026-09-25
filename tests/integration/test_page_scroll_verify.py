"""page_scroll verifies movement before claiming scrolled: true (E2E).

The bug: to_element and direction returned scrolled:true unconditionally — on a
page that fits the viewport (nothing scrollable) they claimed success while
nothing moved, so the caller believed it was looking at a different part of the
page. Both now compare a scroll signature before/after and return
scrolled:false + reason when nothing moved (as to_bottom already did).
Launches a real headless Chrome.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib

import pytest

from ai_dev_browser.core import connect_browser, get_active_tab
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.elements import page_scroll

_FLAT = (
    "<!doctype html><meta charset=utf-8><body style='margin:0'>"
    "<p id=only>fits the viewport</p></body>"
)
_TALL = (
    "<!doctype html><meta charset=utf-8><body style='margin:0'>"
    "<div style='height:6000px'>top</div><div id=bot>BOTTOM</div></body>"
)


@pytest.fixture
async def tab():
    result = browser_start(headless=True, temp=True, reuse="none")
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


async def _load(tab, html):
    await tab.get("data:text/html;base64," + base64.b64encode(html.encode()).decode())
    await asyncio.sleep(0.3)


@pytest.mark.asyncio
async def test_direction_scroll_reports_false_when_nothing_moves(tab):
    await _load(tab, _FLAT)
    res = await page_scroll(tab, direction="down", amount=12000)
    assert res.get("scrolled") is False, res
    assert "reason" in res, res


@pytest.mark.asyncio
async def test_to_element_reports_false_when_already_in_view(tab):
    await _load(tab, _FLAT)
    res = await page_scroll(tab, to_element="fits the viewport")
    assert res.get("scrolled") is False, res
    # found:True disambiguates "already in view (proceed)" from "not located"
    assert res.get("found") is True and res.get("target"), res
    assert "reason" in res, res


@pytest.mark.asyncio
async def test_to_element_missing_reports_found_false(tab):
    await _load(tab, _FLAT)
    res = await page_scroll(tab, to_element="NONEXISTENT_ZZZ")
    assert res.get("scrolled") is False and res.get("found") is False, res


@pytest.mark.asyncio
async def test_direction_scroll_reports_true_when_it_moves(tab):
    await _load(tab, _TALL)
    res = await page_scroll(tab, direction="down", amount=90)
    assert res.get("scrolled") is True, res


@pytest.mark.asyncio
async def test_to_element_reports_true_when_it_moves(tab):
    await _load(tab, _TALL)
    res = await page_scroll(tab, to_element="BOTTOM")
    assert res.get("scrolled") is True and res.get("found") is True, res
