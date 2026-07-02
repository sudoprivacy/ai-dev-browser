"""Regression: page_scroll must work on embedded CDP targets that
don't implement Chrome's `Browser` domain (Electron / CEF / packaged
Chromium apps exposing CDP via `--remote-debugging-port`).

Pre-fix, `page_scroll(direction="down")` walked:
  page_scroll → tab.scroll_down → tab.get_window (Browser.getWindowForTarget)

That CDP method is Chrome-browser-specific; embedded targets return
`-32601 Method not found` and the whole scroll path aborts. Reported
by a downstream integrator attaching to a packaged Electron app.

Fix (in `_tab.py`): rewrite `scroll_down` / `scroll_up` to use
`Runtime.evaluate` with `window.scrollBy(0, window.innerHeight * pct)`.
Runtime is universally supported. Bounds lookup and gesture
synthesis (Browser + Input.synthesizeScrollGesture) removed from the
scroll path entirely.

Tests below verify BOTH sides of the contract:
  1. Positive — scroll_down actually scrolls a real Chrome fixture
     (proves the JS-based rewrite works).
  2. Negative — scroll_down succeeds even if `tab.get_window` is
     patched to raise (proves the code path no longer depends on
     the Browser-domain call that fails on Electron).

The negative test is the load-bearing one: without it, a future
"cleanup" that reintroduces `get_window()` in the scroll path would
silently re-break Electron users and CI wouldn't notice (regular
Chrome has getWindowForTarget so the code would appear to work).
"""

from __future__ import annotations

import base64
import contextlib
import os

import pytest

from ai_dev_browser.core import page_goto, page_scroll
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


@pytest.fixture
async def tab():
    """Headless Chrome loaded with a tall data:URL so scrollY has
    room to change. Deliberately >5x viewport so a 25% scroll is a
    detectable delta."""
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    browser_client = None
    try:
        browser_client = await connect_browser(port=port)
        the_tab = await get_active_tab(browser_client)
        html = (
            "<html><body style='margin:0'>"
            + "".join(
                f"<div style='height:200px;background:hsl({i * 37 % 360},60%,50%);"
                f"color:white;padding:20px;font-size:22px'>Row {i}</div>"
                for i in range(30)
            )
            + "</body></html>"
        )
        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await page_goto(the_tab, data_url)
        yield the_tab
    finally:
        if browser_client is not None:
            with contextlib.suppress(Exception):
                await browser_client.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


async def _get_scroll_y(tab) -> float:
    """Read window.scrollY through the same Runtime.evaluate channel
    the fix uses — deep-serialization deserialization of a numeric
    RemoteObject varies, so pull via .value from the eval envelope."""
    result = await tab.evaluate("window.scrollY", return_by_value=True)
    return float(result if result is not None else 0)


async def test_page_scroll_down_actually_scrolls(tab):
    """Positive: real headless Chrome + tall fixture → scroll_down
    must observably move window.scrollY forward. Baseline that proves
    the JS-based rewrite works at all before we go asserting Electron
    compat."""
    before = await _get_scroll_y(tab)
    assert before == 0, f"fixture should start at scrollY=0, got {before}"

    ok = await page_scroll(tab, direction="down", amount=50)
    assert ok is True

    after = await _get_scroll_y(tab)
    assert after > before, (
        f"scroll_down(50%) did not move scrollY: before={before}, after={after}"
    )


async def test_page_scroll_up_after_down_reverses(tab):
    """Positive: scroll_up unwinds a prior scroll_down. Two-step
    verifies the sign convention (positive percent = down / content
    moves up) is preserved after the rewrite — a reversed sign would
    slip past 'did it scroll?' asserts."""
    await page_scroll(tab, direction="down", amount=50)
    peak = await _get_scroll_y(tab)
    assert peak > 0

    await page_scroll(tab, direction="up", amount=50)
    after_up = await _get_scroll_y(tab)
    assert after_up < peak, (
        f"scroll_up did not reduce scrollY: peak={peak}, after_up={after_up}"
    )


async def test_page_scroll_survives_broken_get_window(tab, monkeypatch):
    """Regression pin: even if `tab.get_window` is completely broken —
    the exact failure mode Electron / embedded targets exhibit —
    page_scroll must still work. The rewrite guarantees this by never
    calling get_window() from the scroll path.

    If a future edit reintroduces `get_window()` into scroll_down or
    a helper it calls, this test will fail on ProtocolException before
    the scroll runs. That's the whole point — Electron users would
    otherwise be silently broken again because regular Chrome CI
    always has getWindowForTarget so the code would look green."""

    async def _boom():
        raise RuntimeError(
            "Browser.getWindowForTarget wasn't found — simulated Electron target"
        )

    monkeypatch.setattr(tab, "get_window", _boom)

    before = await _get_scroll_y(tab)
    ok = await page_scroll(tab, direction="down", amount=50)
    assert ok is True

    after = await _get_scroll_y(tab)
    assert after > before, (
        f"scroll_down with get_window broken failed to scroll: "
        f"before={before}, after={after}"
    )


async def test_page_scroll_to_bottom_survives_broken_get_window(tab, monkeypatch):
    """The other two page_scroll branches (to_bottom / to_top) already
    used tab.evaluate, so they should already work on embedded
    targets. This test pins that assumption so a future refactor
    doesn't route them through get_window()."""

    async def _boom():
        raise RuntimeError("simulated Electron: Browser domain unavailable")

    monkeypatch.setattr(tab, "get_window", _boom)

    ok = await page_scroll(tab, to_bottom=True)
    assert ok is True

    after = await _get_scroll_y(tab)
    assert after > 500, (
        f"to_bottom should scroll a 6000px page substantially; got scrollY={after}"
    )
