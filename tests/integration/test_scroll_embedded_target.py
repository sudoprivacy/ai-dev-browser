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

import asyncio
import base64
import contextlib
import json
import os
import subprocess
import sys
import urllib.parse

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
    assert ok["scrolled"] is True

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
    assert ok["scrolled"] is True

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
    assert ok["scrolled"] is True
    assert ok["target"] == "window", f"expected top-window scroll, got {ok}"

    after = await _get_scroll_y(tab)
    assert after > 500, (
        f"to_bottom should scroll a 6000px page substantially; got scrollY={after}"
    )


# ---------------------------------------------------------------------------
# Bug-report regressions (page_scroll · 2 bugs)
#   Bug 1: `to_element="<text>"` threw `'str' object has no attribute
#          scroll_into_view` — the CLI passes a string, the core expected a
#          pre-resolved Element. Now the string is resolved to an element.
#   Bug 2: `to_bottom` on iframe-wrapped content returned scrolled=True but
#          did nothing — it scrolled the top window, which isn't the scroller.
#          Now it finds the real scroller (same-origin iframe) and fails loud
#          when nothing is scrollable at all.
# ---------------------------------------------------------------------------


async def _data_url(html: str) -> str:
    return "data:text/html;base64," + base64.b64encode(html.encode()).decode()


async def _iframe_scroll_room(tab, selector: str) -> float:
    """Vertical scroll room (px) inside a same-origin iframe's document —
    used to wait out srcdoc layout before asserting on scroll behavior."""
    js = (
        "(() => { const f = document.querySelector(" + repr(selector) + ");"
        " const d = f && f.contentDocument;"
        " const s = d && (d.scrollingElement || d.documentElement);"
        " return s ? s.scrollHeight - s.clientHeight : 0; })()"
    )
    return float(await tab.evaluate(js, return_by_value=True) or 0)


async def _wait_iframe_room(tab, selector: str, minimum: float = 500) -> float:
    """Poll until the iframe has laid out `minimum` px of scroll room."""
    for _ in range(20):
        room = await _iframe_scroll_room(tab, selector)
        if room > minimum:
            return room
        await asyncio.sleep(0.1)
    return await _iframe_scroll_room(tab, selector)


async def test_page_scroll_to_element_by_text_resolves_string(tab):
    """Bug 1: a *text* target (what the CLI always passes) must resolve to
    an element and scroll it into view — not blow up with
    `'str' object has no attribute 'scroll_into_view'`. The fixture page is
    6000px tall with 'Row N' landmarks, so scrolling to a late row moves
    scrollY forward from the top."""
    before = await _get_scroll_y(tab)
    assert before == 0

    ok = await page_scroll(tab, to_element="Row 28")
    assert ok["scrolled"] is True, f"to_element by text failed: {ok}"

    after = await _get_scroll_y(tab)
    assert after > before, (
        f"to_element='Row 28' did not scroll it into view: "
        f"before={before}, after={after}"
    )


async def test_page_scroll_to_bottom_scrolls_same_origin_iframe(tab):
    """Bug 2: when the page body fits the viewport but its content lives in
    a (same-origin) iframe, `to_bottom` must scroll the *iframe*, not
    silent-no-op on the un-scrollable top window."""
    inner = (
        "<body style='margin:0'>"
        + "".join(f"<div style='height:200px'>Inner {i}</div>" for i in range(30))
        + "</body>"
    )
    outer = (
        "<html><body style='margin:0'>"
        f'<iframe id="viewer" style="width:100%;height:300px;border:0" '
        f'srcdoc="{inner}"></iframe>'
        "</body></html>"
    )
    await page_goto(tab, await _data_url(outer))

    # Wait for the same-origin iframe document to lay out scroll room.
    assert await _wait_iframe_room(tab, "#viewer") > 500, (
        "iframe fixture never gained scroll room"
    )

    top_before = await _get_scroll_y(tab)
    ok = await page_scroll(tab, to_bottom=True)

    assert ok["scrolled"] is True, f"iframe to_bottom reported no scroll: {ok}"
    assert "iframe" in ok["target"], (
        f"expected the iframe to be the scroll target, got target={ok.get('target')!r}"
    )
    # Top window never moved (it can't) — the scroll happened inside the frame.
    assert await _get_scroll_y(tab) == top_before

    inner_top = await tab.evaluate(
        "document.querySelector('#viewer').contentDocument.scrollingElement.scrollTop",
        return_by_value=True,
    )
    assert float(inner_top or 0) > 500, (
        f"iframe content did not scroll to bottom: scrollTop={inner_top}"
    )


async def test_page_scroll_to_bottom_fails_loud_when_nothing_scrollable(tab):
    """Bug 2 (other half): a page that fits the viewport has nothing to
    scroll. `to_bottom` must say so — `scrolled: False` with a reason —
    rather than the old unconditional `True`."""
    short = "<html><body style='margin:0'><p>tiny page</p></body></html>"
    await page_goto(tab, await _data_url(short))

    ok = await page_scroll(tab, to_bottom=True)
    assert ok["scrolled"] is False, f"expected fail-loud, got {ok}"
    assert "scrollable" in ok.get("reason", ""), (
        f"reason should explain nothing was scrollable, got {ok.get('reason')!r}"
    )


async def test_page_scroll_to_element_reaches_same_origin_iframe(tab):
    """The reporter's real goal: reach a landmark ('Appendix A') that lives
    inside the doc-viewer's same-origin iframe. `to_element` resolves the
    text with the same accessible-name locator `find_by_text` uses (which
    spans same-origin iframes), then scrolls the *iframe* to bring it into
    view — the top window can't reach it."""
    marker = "APPENDIX-A-MARKER"
    inner = (
        "<body style='margin:0'>"
        + "".join(f"<div style='height:200px'>pad {i}</div>" for i in range(30))
        + f"<div id='mark'>{marker}</div></body>"
    )
    outer = (
        '<html><body style="margin:0">'
        '<iframe id="viewer" style="width:100%;height:300px;border:0" '
        f'srcdoc="{inner}"></iframe></body></html>'
    )
    await page_goto(tab, await _data_url(outer))

    assert await _wait_iframe_room(tab, "#viewer") > 500, (
        "iframe fixture never gained scroll room"
    )

    ok = await page_scroll(tab, to_element=marker)
    assert ok["scrolled"] is True, f"to_element across iframe failed: {ok}"

    inner_top = await tab.evaluate(
        "document.querySelector('#viewer').contentDocument.scrollingElement.scrollTop",
        return_by_value=True,
    )
    assert float(inner_top or 0) > 500, (
        f"iframe did not scroll to bring {marker!r} into view: scrollTop={inner_top}"
    )


async def test_page_scroll_to_bottom_reports_cross_origin_iframe(tab):
    """A cross-origin iframe's document is unreachable from JS, so
    `to_bottom` cannot scroll it — but it must say *why* (fail loud +
    steer to the gesture path), not silent-succeed. Reproduced
    hermetically with a data: iframe inside a data: page: two distinct
    opaque origins, so `contentDocument` access throws exactly as a real
    cross-origin embed would."""
    inner_html = "<body style='margin:0'><div style='height:5000px'>x</div></body>"
    inner_src = "data:text/html," + urllib.parse.quote(inner_html)
    outer = (
        '<html><body style="margin:0">'
        f'<iframe style="width:100%;height:200px;border:0" src="{inner_src}"></iframe>'
        "</body></html>"
    )
    await page_goto(tab, await _data_url(outer))

    ok = await page_scroll(tab, to_bottom=True)
    assert ok["scrolled"] is False, f"expected fail-loud on cross-origin, got {ok}"
    assert "cross-origin" in ok.get("reason", ""), (
        f"reason should call out the cross-origin iframe, got {ok.get('reason')!r}"
    )


async def test_page_scroll_to_element_via_real_cli_boundary():
    """Bug 1 lived at the CLI boundary: `page_scroll --to-element "<text>"`
    handed a *string* to a core that expected an Element, printing
    `{"error": "'str' object has no attribute 'scroll_into_view'"}`. The
    Python-level tests above pass a str too, but only a real subprocess
    exercises argv → argparse → wrap_core → core → JSON stdout — the exact
    surface the bug was reported on. Drive it against a live browser."""
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    browser_client = None
    try:
        browser_client = await connect_browser(port=port)
        the_tab = await get_active_tab(browser_client)
        html = (
            "<html><body style='margin:0'>"
            + "".join(f"<div style='height:200px'>Row {i}</div>" for i in range(30))
            + "</body></html>"
        )
        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await page_goto(the_tab, data_url)
        # Hand the browser to the CLI cleanly — it connects fresh by --port.
        await browser_client.close()
        browser_client = None

        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "ai_dev_browser.tools.page_scroll",
                "--to-element",
                "Row 28",
                "--port",
                str(port),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1"},
            timeout=90,
        )
        assert proc.returncode == 0, (
            f"CLI exited {proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )
        out = json.loads(proc.stdout)
        assert out.get("scrolled") is True, f"expected scrolled:true, got {out}"
        assert out.get("target") == "Row 28", f"unexpected target: {out}"
        # The exact pre-fix failure string must never reappear.
        assert "scroll_into_view" not in proc.stdout, (
            f"the Bug 1 AttributeError leaked back: {proc.stdout}"
        )
    finally:
        if browser_client is not None:
            with contextlib.suppress(Exception):
                await browser_client.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)
