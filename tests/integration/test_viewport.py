"""Every tab opens at a desktop render viewport by default, so responsive web
apps render their DESKTOP layout instead of collapsing to mobile/compact.

Reported by a downstream integrator: ai-dev-browser's Chrome defaulted to
`innerWidth≈764` / `screen.width=800`. At that width enterprise apps switch to
a mobile layout — 金蝶云星空 flips its URL to `formType=mobileform`, hiding the
whole desktop nav / search / report tree; 电子税务局 does the same — so
automation has nothing to click. The empirically-proven lever is the RENDER
viewport (`Emulation.setDeviceMetricsOverride`), not the OS window: the window
can't exceed a small virtual display, but the render viewport can.

The fixture is a media-query page that shows `#desktop` at ≥1000px and
`#mobile` below it — the same breakpoint mechanism the real apps use — so the
tests assert on which layout actually rendered, not just on a number.
"""

from __future__ import annotations

import base64
import os

import pytest

from ai_dev_browser.core import cdp_send, js_evaluate, page_goto, window_set
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.config import (
    DEFAULT_VIEWPORT_HEIGHT,
    DEFAULT_VIEWPORT_WIDTH,
    VIEWPORT_ENV,
    resolve_viewport,
)
from ai_dev_browser.core.connection import connect_browser, get_active_tab

SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)

_FIXTURE = """<!doctype html><meta charset=utf-8><style>
 #desktop{display:none} #mobile{display:block}
 @media (min-width:1000px){#desktop{display:block}#mobile{display:none}}
</style><body>
 <div id=desktop>DESKTOP-NAV</div><div id=mobile>MOBILE-NAV</div>
</body>"""
_URL = "data:text/html;base64," + base64.b64encode(_FIXTURE.encode()).decode()


# --------------------------------------------------------------------------- #
# resolve_viewport() — pure logic, no browser (always runs)
# --------------------------------------------------------------------------- #


def test_resolve_viewport_default(monkeypatch):
    monkeypatch.delenv(VIEWPORT_ENV, raising=False)
    assert resolve_viewport() == (DEFAULT_VIEWPORT_WIDTH, DEFAULT_VIEWPORT_HEIGHT)


def test_resolve_viewport_custom_size(monkeypatch):
    monkeypatch.setenv(VIEWPORT_ENV, "1280x720")
    assert resolve_viewport() == (1280, 720)


@pytest.mark.parametrize("value", ["native", "off", "0", "NONE", "False"])
def test_resolve_viewport_disabled(monkeypatch, value):
    monkeypatch.setenv(VIEWPORT_ENV, value)
    assert resolve_viewport() is None


def test_resolve_viewport_malformed_fails_loud(monkeypatch):
    """A set-but-unparseable viewport raises rather than silently defaulting —
    an explicitly-requested viewport that's ignored is the worst outcome."""
    monkeypatch.setenv(VIEWPORT_ENV, "1600")  # missing height
    with pytest.raises(ValueError, match="WIDTHxHEIGHT"):
        resolve_viewport()


# --------------------------------------------------------------------------- #
# Browser-backed — the real wiring
# --------------------------------------------------------------------------- #


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


async def _dims(tab) -> dict:
    r = await js_evaluate(
        tab, "({iw: innerWidth, sw: screen.width, dpr: devicePixelRatio})"
    )
    return r["result"]


async def _visible_nav(tab) -> str:
    r = await js_evaluate(
        tab,
        "getComputedStyle(document.getElementById('desktop')).display !== 'none'"
        " ? 'DESKTOP' : 'MOBILE'",
    )
    return r["result"]


async def test_default_viewport_is_desktop(port, monkeypatch):
    """The core fix: with no override configured, a freshly-acquired tab renders
    the DESKTOP layout — the reporter's blocker, gone."""
    monkeypatch.delenv(VIEWPORT_ENV, raising=False)
    browser = await connect_browser(port=port)
    try:
        tab = await get_active_tab(browser)  # default viewport applied here
        await page_goto(tab, _URL)
        dims = await _dims(tab)
        assert dims["iw"] >= 1440, f"innerWidth should be desktop-class: {dims}"
        assert dims["sw"] >= 1440, f"screen.width should follow too: {dims}"
        assert dims["dpr"] == 1, f"deviceScaleFactor 1 keeps screenshots 1:1: {dims}"
        assert await _visible_nav(tab) == "DESKTOP"
    finally:
        await browser.close()


async def test_window_set_changes_the_render_viewport(port, monkeypatch):
    """window_set(width=...) moves the RENDER viewport (innerWidth), not just an
    OS window frame — so a narrow width really reproduces the mobile layout.
    Guards against the old silent no-op the reporter hit."""
    monkeypatch.delenv(VIEWPORT_ENV, raising=False)
    browser = await connect_browser(port=port)
    try:
        tab = await get_active_tab(browser)
        await page_goto(tab, _URL)
        assert await _visible_nav(tab) == "DESKTOP"  # default

        result = await window_set(tab, width=390, height=844)
        assert result["width"] == 390, result
        dims = await _dims(tab)
        assert dims["iw"] == 390, f"innerWidth must follow window_set: {dims}"
        assert await _visible_nav(tab) == "MOBILE", "narrow viewport should flip layout"
    finally:
        await browser.close()


async def test_env_native_opts_out_in_a_real_browser(port, monkeypatch):
    """AI_DEV_BROWSER_VIEWPORT=native leaves Chrome's own small viewport in
    place — proves the switch flows all the way to the tab, not just to
    resolve_viewport()."""
    monkeypatch.setenv(VIEWPORT_ENV, "native")
    browser = await connect_browser(port=port)
    try:
        tab = await get_active_tab(browser)  # no override applied
        await page_goto(tab, _URL)
        dims = await _dims(tab)
        assert dims["iw"] < 1000, f"native viewport should stay small: {dims}"
        assert await _visible_nav(tab) == "MOBILE"
    finally:
        await browser.close()


async def test_cdp_send_accepts_camelcase_params(port, monkeypatch):
    """cdp_send takes CDP-native camelCase (`deviceScaleFactor`) verbatim from
    the protocol docs — no more unexpected-kwarg error for snake_case-only."""
    monkeypatch.delenv(VIEWPORT_ENV, raising=False)
    browser = await connect_browser(port=port)
    try:
        tab = await get_active_tab(browser)
        await page_goto(tab, _URL)
        out = await cdp_send(
            tab,
            "Emulation.setDeviceMetricsOverride",
            '{"width":1440,"height":900,"deviceScaleFactor":1,"mobile":false,'
            '"screenWidth":1440,"screenHeight":900}',
        )
        assert "error" not in out, f"camelCase params must not error: {out}"
        dims = await _dims(tab)
        assert dims["iw"] == 1440, f"the override should have applied: {dims}"
    finally:
        await browser.close()
