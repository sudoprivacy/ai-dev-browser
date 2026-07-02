"""Regression: page_scroll must work on embedded CDP targets that
don't implement Chrome's `Browser` domain (Electron / CEF / packaged
Chromium apps exposing CDP via `--remote-debugging-port`).

Pre-fix, `page_scroll(direction="down")` walked:
  page_scroll → tab.scroll_down → tab.get_window (Browser.getWindowForTarget)

That CDP method is Chrome-browser-specific; embedded targets return
`-32601 Method not found` and the whole scroll path aborts. Reported
by a downstream integrator attaching to a packaged Electron app.

Fix (in `_tab._scroll_by_viewport_percent`): try the Chrome
gesture path first (`get_window` + `synthesize_scroll_gesture` —
still the preferred path because gesture-shape acceleration helps
evade anti-bot heuristics that flag instant scroll jumps). If that
returns CDP `-32601 method not found`, fall back to
`Runtime.evaluate` + `window.scrollBy` — Runtime is universally
supported. Any OTHER ProtocolException still surfaces so real
protocol violations aren't silently downgraded to the fallback.

Tests below pin all three contracts:
  1. Positive — scroll_down actually scrolls a real Chrome fixture
     via the gesture path (proves it wasn't broken by the fallback
     plumbing).
  2. Fallback — scroll_down succeeds when `get_window` is patched
     to raise `-32601 method not found` (proves the embedded-target
     path works).
  3. Guardrail — a NON-32601 ProtocolException must NOT be
     downgraded to fallback (proves we didn't paper over real
     protocol bugs).

Tests 2 + 3 are the load-bearing pair — without them a future
"cleanup" could either reintroduce `get_window()` in the fallback
path (re-breaking Electron users) or widen the except-clause to
swallow all protocol errors (masking real bugs), and regular Chrome
CI would go green for both regressions.
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


async def test_page_scroll_falls_back_on_cdp_method_not_found(tab, monkeypatch):
    """The Electron path: `get_window` raises CDP -32601 'method not
    found' → scroll must fall back to `window.scrollBy` via
    Runtime.evaluate and still scroll.

    Simulating the failure mode with the actual `ProtocolException`
    shape the CDP transport produces (dict with `code: -32601`), not
    a generic Exception — otherwise a future edit narrowing the
    except-clause to only catch method-not-found would break this
    test and force a re-think, which is exactly the point."""
    from ai_dev_browser.core._transport import ProtocolException

    async def _boom():
        raise ProtocolException(
            {"code": -32601, "message": "'Browser.getWindowForTarget' wasn't found"}
        )

    monkeypatch.setattr(tab, "get_window", _boom)

    before = await _get_scroll_y(tab)
    ok = await page_scroll(tab, direction="down", amount=50)
    assert ok is True

    after = await _get_scroll_y(tab)
    assert after > before, (
        f"scroll_down did not fall back to JS scroll on -32601: "
        f"before={before}, after={after}"
    )


async def test_page_scroll_does_not_swallow_other_protocol_errors(tab, monkeypatch):
    """Guardrail: only -32601 method-not-found triggers fallback. A
    different CDP error (say a target crash, code -32000, or protocol
    violation) must NOT be silently downgraded to the JS path —
    that would mask real bugs in the transport / gesture pipeline.

    Without this test, a maintainer could widen the except clause to
    `except ProtocolException:` (catch-all) and Chrome CI would go
    green, but any transport-layer failure would silently succeed
    with a JS fallback — losing observability of a real bug."""
    from ai_dev_browser.core._transport import ProtocolException

    async def _boom():
        # -32000 is a generic server error, NOT method-not-found.
        raise ProtocolException(
            {"code": -32000, "message": "Target crashed while loading window bounds"}
        )

    monkeypatch.setattr(tab, "get_window", _boom)

    with pytest.raises(ProtocolException) as ei:
        await page_scroll(tab, direction="down", amount=50)
    assert ei.value.args[0].get("code") == -32000, (
        f"expected -32000 to propagate, got: {ei.value.args}"
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
