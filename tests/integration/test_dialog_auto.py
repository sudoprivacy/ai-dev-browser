"""JS dialogs are auto-handled by default, so automation never wedges on one.

An open `alert()` / `confirm()` / `prompt()` blocks the render main thread, so
ANY renderer command hangs until it's answered — the reported wall on a
government SPA where `page_screenshot` / `js_evaluate` all hung to timeout after
a click fired a dialog, with no way to even detect the dialog (the probe hung
too). ai-dev-browser now registers a dialog handler at tab setup (like
Playwright/Puppeteer): dialogs are dismissed the moment they open.

The tests are deterministic because `js_evaluate("confirm('x')")` *cannot
return* while the dialog is open — if it comes back at all, the dialog was
handled. The `off` test pins the contrast: without auto-handling it really does
hang.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from ai_dev_browser.core import js_evaluate, page_goto
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.config import DIALOG_ENV
from ai_dev_browser.core.connection import connect_browser, get_active_tab

SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)

_URL = "data:text/html;charset=utf-8,<title>dialogs</title>"


@pytest.fixture
def port():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    try:
        yield port
    finally:
        browser_stop(port=port)


async def _tab(port):
    """Fresh connection + prepared tab (registers the dialog handler per the
    env policy in effect at this call)."""
    browser = await connect_browser(port=port)
    tab = await get_active_tab(browser)
    await page_goto(tab, _URL)
    return browser, tab


async def test_confirm_auto_dismissed_by_default(port, monkeypatch):
    """Default policy dismisses: `confirm()` returns False AND — the whole point
    — the eval returns at all instead of hanging on the open dialog."""
    monkeypatch.delenv(DIALOG_ENV, raising=False)
    browser, tab = await _tab(port)
    try:
        res = await asyncio.wait_for(js_evaluate(tab, "confirm('go?')"), timeout=15)
        assert res["result"] is False, res
    finally:
        await browser.close()


async def test_alert_does_not_block(port, monkeypatch):
    """`alert()` has no answer to give, but must not wedge the renderer — the
    expression after it still evaluates."""
    monkeypatch.delenv(DIALOG_ENV, raising=False)
    browser, tab = await _tab(port)
    try:
        res = await asyncio.wait_for(js_evaluate(tab, "alert('hi'); 42"), timeout=15)
        assert res["result"] == 42, res
    finally:
        await browser.close()


async def test_confirm_auto_accepted_with_env(port, monkeypatch):
    """AI_DEV_BROWSER_DIALOG=accept flips the default to OK/Yes — needed for
    flows that must proceed through a confirm (e.g. a download prompt)."""
    monkeypatch.setenv(DIALOG_ENV, "accept")
    browser, tab = await _tab(port)
    try:
        res = await asyncio.wait_for(js_evaluate(tab, "confirm('go?')"), timeout=15)
        assert res["result"] is True, res
    finally:
        await browser.close()


async def test_off_disables_autohandling_and_confirm_blocks(port, monkeypatch):
    """The contrast that justifies the default: with auto-handling off, an open
    confirm() really does block the renderer, so the eval never returns."""
    monkeypatch.setenv(DIALOG_ENV, "off")
    browser, tab = await _tab(port)
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(js_evaluate(tab, "confirm('go?')"), timeout=4)
    finally:
        # The renderer is wedged on the open dialog; drop the connection and let
        # browser_stop kill the process (a clean close would itself hang).
        with __import__("contextlib").suppress(Exception):
            await asyncio.wait_for(browser.close(), timeout=3)
