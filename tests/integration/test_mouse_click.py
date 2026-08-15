"""`mouse_click` must FAIL LOUD, not hang, when a page's mouse handler blocks
the render thread — the reported wall on heavy enterprise SPAs (Kingdee BOS).

CDP `Input.dispatchMouseEvent`'s response waits on the page dispatching the
event to its handler; if that handler blocks the main thread (a synchronous
recalc, a modal), the response stalls. At the 30s default command timeout that
reads as a hang, and a humanized move fires many dispatches back-to-back. Each
mouse dispatch is now bounded by MOUSE_EVENT_TIMEOUT, so a stuck handler raises
in ~5s instead of hanging; `move=False` cuts the pre-click events entirely.

The fixture's mousedown handler busy-loops for `__blockMs` ms — a faithful
stand-in for a blocking SPA handler — so the tests assert on real timing.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import os

import pytest

from ai_dev_browser.core import mouse_click, page_goto
from ai_dev_browser.core._transport import COMMAND_TIMEOUT, CommandTimeout
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


# A full-viewport target. mousedown optionally busy-loops the main thread for
# `window.__blockMs` — the blocking-handler pathology — while click just counts.
_FIXTURE = """<!doctype html><meta charset=utf-8><body style="margin:0">
<div id="t" style="position:absolute;left:0;top:0;width:600px;height:600px"></div>
<script>
  window.__clicked = 0;
  window.__blockMs = 0;
  const t = document.getElementById('t');
  t.addEventListener('mousedown', () => {
    if (window.__blockMs) { const s = Date.now(); while (Date.now() - s < window.__blockMs) {} }
  });
  t.addEventListener('click', () => { window.__clicked++; });
</script></body>"""
_URL = "data:text/html;base64," + base64.b64encode(_FIXTURE.encode()).decode()


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


async def _clicked(tab) -> int:
    return await tab.evaluate("window.__clicked", return_by_value=True)


async def test_normal_click_fires(tab):
    """Baseline: a plain click at coordinates fires the page's click handler."""
    assert await mouse_click(tab, 50, 50) is True
    assert await _clicked(tab) == 1


async def test_click_with_move_false_still_fires(tab):
    """move=False skips the pre-click cursor move but still presses+releases, so
    the click lands — the robust path for heavy SPAs."""
    assert await mouse_click(tab, 60, 60, move=True) is True
    assert await mouse_click(tab, 60, 60, move=False) is True
    assert await _clicked(tab) == 2


async def test_blocking_handler_fails_loud_fast_not_hang(tab):
    """The reported failure: a mousedown handler that blocks the render thread.
    The click must raise (bounded mouse-event timeout) in well under the 30s
    default command timeout — not hang until the caller kills it."""
    loop = asyncio.get_running_loop()
    # Block far longer than MOUSE_EVENT_TIMEOUT so the dispatch response stalls.
    await tab.evaluate("window.__blockMs = 20000", return_by_value=True)

    start = loop.time()
    with pytest.raises(CommandTimeout):
        await mouse_click(tab, 100, 100, move=False)
    elapsed = loop.time() - start

    assert elapsed < COMMAND_TIMEOUT - 5, (
        f"click should fail on the mouse-event timeout (~5s), not the {COMMAND_TIMEOUT}s "
        f"default — took {elapsed:.1f}s"
    )
