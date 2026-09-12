"""browser_start timezone/geo overrides survive adb's per-call session model.

The bug this guards: Emulation.* overrides are per-CDP-session and every tool
call attaches a fresh session, so a one-shot override vanishes by the next call
/ new tab / navigation. browser_start records the identity; get_active_tab
re-asserts it every acquisition. Launches a real headless Chrome (E2E).
"""

from __future__ import annotations

import contextlib

import pytest

from ai_dev_browser.core import connect_browser, get_active_tab
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.identity import build_identity, parse_geo


def test_parse_geo():
    assert parse_geo("35.68,139.69") == [35.68, 139.69]
    assert parse_geo(" 1.5 , -2.0 ") == [1.5, -2.0]
    assert parse_geo(None) is None
    assert parse_geo("not-a-coord") is None
    assert parse_geo("35.68") is None


def test_build_identity_omits_empty_and_keeps_language_opt_in():
    assert build_identity() is None  # nothing set -> no identity stored
    assert build_identity(timezone="Asia/Tokyo") == {"timezone": "Asia/Tokyo"}
    assert build_identity(geo=[1.0, 2.0]) == {"geo": [1.0, 2.0]}
    # locale only appears when explicitly set (never auto-derived).
    full = build_identity(timezone="Asia/Tokyo", geo=[1.0, 2.0], locale="ja-JP")
    assert full == {"timezone": "Asia/Tokyo", "geo": [1.0, 2.0], "locale": "ja-JP"}


async def _tz(tab):
    return await tab.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")


@pytest.mark.asyncio
async def test_timezone_survives_fresh_acquisition_new_tab_and_nav():
    r = browser_start(
        headless=True,
        temp=True,
        reuse="none",
        timezone="Asia/Tokyo",
        geo="35.68,139.69",
    )
    assert "error" not in r, r
    assert r.get("identity_consistent") is True and r.get("timezone") == "Asia/Tokyo", r
    assert r.get("geolocation") == [35.68, 139.69], r
    port = r["port"]
    browser = None
    try:
        browser = await connect_browser(port=port)

        # (1) fresh acquisition re-asserts the override
        tab = await get_active_tab(browser)
        assert await _tz(tab) == "Asia/Tokyo"

        # (2) a NEW tab still sees it (fresh acquisition re-asserts on it too)
        await browser.get("https://example.com")
        tab2 = await get_active_tab(browser, url_contains="example.com")
        assert await _tz(tab2) == "Asia/Tokyo"

        # (3) after navigating that tab to another domain it still holds (the
        # per-session override survives navigation within the session)
        await tab2.get("https://example.org")
        assert await _tz(tab2) == "Asia/Tokyo"
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


@pytest.mark.asyncio
async def test_no_identity_args_leaves_host_timezone_and_no_fields():
    r = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in r, r
    assert "identity_consistent" not in r and "timezone" not in r, r
    with contextlib.suppress(Exception):
        browser_stop(port=r["port"])
