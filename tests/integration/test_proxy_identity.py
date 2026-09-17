"""browser_start timezone/geo overrides survive adb's per-call session model.

The bug this guards: Emulation.* overrides are per-CDP-session and every tool
call attaches a fresh session, so a one-shot override vanishes by the next call
/ new tab / navigation. browser_start records the identity; get_active_tab
re-asserts it every acquisition. Launches a real headless Chrome (E2E).
"""

from __future__ import annotations

import contextlib

import pytest

import ai_dev_browser.core.identity as identity_mod
from ai_dev_browser.core import connect_browser, get_active_tab
from ai_dev_browser.core.browser import (
    _resolve_do_match,
    _with_lang_arg,
    browser_start,
    browser_stop,
)
from ai_dev_browser.core.identity import build_identity, parse_geo, parse_geo_json


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


def test_with_lang_arg_injects_and_respects_caller():
    assert _with_lang_arg(None, "en-SG") == ["--lang=en-SG"]
    assert _with_lang_arg(["--foo"], "ja-JP") == ["--foo", "--lang=ja-JP"]
    # a --lang the caller already passed wins (not doubled)
    assert _with_lang_arg(["--lang=fr-FR"], "en-SG") == ["--lang=fr-FR"]
    # no locale -> untouched (None stays None)
    assert _with_lang_arg(None, None) is None
    assert _with_lang_arg(["--foo"], None) == ["--foo"]


@pytest.mark.asyncio
async def test_locale_actually_moves_navigator_language_and_reports_landed():
    # The v0.38.0 bug: locale went in via setLocaleOverride (Intl only), so it was
    # reported applied while navigator.language stayed the host default. Now it
    # drives --lang at launch (moves navigator.language) and the return reports
    # the LANDED locale, not the request.
    r = browser_start(headless=True, temp=True, reuse="none", locale="en-SG")
    assert "error" not in r, r
    assert r.get("identity_consistent") is True, r
    landed = r.get("locale")
    assert isinstance(landed, str) and landed.lower().startswith("en"), r
    port = r["port"]
    browser = None
    try:
        browser = await connect_browser(port=port)
        tab = await get_active_tab(browser)
        nav_lang = await tab.evaluate("navigator.language")
        # the reported locale is the one that actually landed (honest report)
        assert nav_lang == landed, (nav_lang, landed)
        # --lang took effect: navigator.language is an en-* locale, not zh-CN
        assert nav_lang.lower().startswith("en"), nav_lang
        # the per-session Intl override carries the precise requested locale
        intl = await tab.evaluate("Intl.DateTimeFormat().resolvedOptions().locale")
        assert intl == "en-SG", intl
        # when Chrome normalized the UI locale, the request is still surfaced
        if landed != "en-SG":
            assert r.get("locale_requested") == "en-SG", r
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


# --- Increment 2: --match-proxy default + fail-soft ------------------------

_PROXY = ["--proxy-server=http://127.0.0.1:11082"]


def test_resolve_do_match_default_and_overrides(monkeypatch):
    monkeypatch.delenv("AI_DEV_BROWSER_MATCH_PROXY", raising=False)
    assert _resolve_do_match(False, None, _PROXY) is True  # default: proxy -> on
    assert _resolve_do_match(True, None, _PROXY) is False  # explicit tz/geo wins
    assert _resolve_do_match(False, None, []) is False  # no proxy -> off
    assert _resolve_do_match(False, True, []) is True  # forced on
    assert _resolve_do_match(False, False, _PROXY) is False  # forced off
    monkeypatch.setenv("AI_DEV_BROWSER_MATCH_PROXY", "0")
    assert _resolve_do_match(False, None, _PROXY) is False  # env off beats default


def test_parse_geo_json_both_schemas():
    ipapi = parse_geo_json(
        '{"timezone":"Asia/Tokyo","lat":35.6,"lon":139.7,"query":"1.2.3.4"}'
    )
    assert ipapi == {
        "timezone": "Asia/Tokyo",
        "ip": "1.2.3.4",
        "lat": 35.6,
        "lon": 139.7,
    }
    ipinfo = parse_geo_json(
        '{"timezone":"Asia/Tokyo","loc":"35.6,139.7","ip":"1.2.3.4"}'
    )
    assert ipinfo == {
        "timezone": "Asia/Tokyo",
        "ip": "1.2.3.4",
        "lat": 35.6,
        "lon": 139.7,
    }
    assert parse_geo_json('{"lat":1,"lon":2}') is None  # no timezone
    assert parse_geo_json("not json") is None


@pytest.mark.asyncio
async def test_match_proxy_success_applies_and_surfaces(monkeypatch):
    # Mock the egress lookup (a real through-proxy lookup is validated by the
    # reporter); assert the matched identity is surfaced AND actually applied.
    async def fake_derive(port, endpoint=None, timeout=15.0):
        return {"timezone": "Asia/Tokyo", "lat": 35.68, "lon": 139.69, "ip": "1.2.3.4"}

    monkeypatch.setattr(identity_mod, "derive_from_proxy", fake_derive)
    r = browser_start(headless=True, temp=True, reuse="none", match_proxy=True)
    assert "error" not in r, r
    assert r.get("identity_consistent") is True, r
    assert r.get("timezone") == "Asia/Tokyo" and r.get("egress_ip") == "1.2.3.4", r
    assert r.get("geolocation") == [35.68, 139.69], r
    port = r["port"]
    browser = None
    try:
        browser = await connect_browser(port=port)
        tab = await get_active_tab(browser)
        assert await _tz(tab) == "Asia/Tokyo"  # matched identity really applied
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


@pytest.mark.asyncio
async def test_match_proxy_failure_fails_loud_not_hard(monkeypatch):
    async def fake_none(port, endpoint=None, timeout=15.0):
        return None

    monkeypatch.setattr(identity_mod, "derive_from_proxy", fake_none)
    r = browser_start(headless=True, temp=True, reuse="none", match_proxy=True)
    assert "error" not in r, "lookup failure must not hard-fail the launch"
    assert r.get("identity_consistent") is False, r
    assert "identity_warning" in r and "inconsistent" in r["identity_warning"].lower()
    with contextlib.suppress(Exception):
        browser_stop(port=r["port"])
