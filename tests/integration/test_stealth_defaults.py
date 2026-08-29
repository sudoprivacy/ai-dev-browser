"""Stealth-by-default: ai-dev-browser is always LLM-as-user and must not
advertise automation to bot detection (Google/Cloudflare).

`browser_start` defaults to `stealth=True`, which drops `--enable-automation`
and `--disable-blink-features=AutomationControlled`. The consequence to prove
here is twofold:

  1. The browser looks real — `navigator.webdriver` is false and no automation
     bars — WITHOUT relying on AutomationControlled (that flag's only job was to
     undo the webdriver flag, at the cost of a warning bar).
  2. Workspace/profile discovery still works. Dropping `--enable-automation`
     makes `Browser.getBrowserCommandLine` return an empty argument list, so the
     old cmdline-readback path is dead under stealth; discovery now goes through
     the GUID-keyed instance registry (core/registry.py). If that regressed,
     every zero-`--port` CLI tool would fail to find the Chrome browser_start
     just launched.

`stealth=False` restores the legacy flags — verified so the opt-out is real.

Runs against real headless Chrome (the `browser` fixture pattern), so it lives
in CI alongside the other browser-driven integration tests.
"""

from __future__ import annotations

import os

import pytest

from ai_dev_browser.core.browser import browser_list, browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, get_active_tab
from ai_dev_browser.core.port import (
    _query_chrome_cmdline,
    _query_chrome_guid,
    find_workspace_chromes,
)
from ai_dev_browser.core import registry


SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


async def _webdriver(port: int):
    b = await connect_browser(port=port)
    try:
        tab = await get_active_tab(b)
        await tab.get("about:blank")
        return await tab.evaluate("navigator.webdriver", return_by_value=True)
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_stealth_default_hides_webdriver_and_stays_discoverable():
    result = browser_start(headless=True, temp=True)
    assert "error" not in result, result
    port = result["port"]
    try:
        # 1. Real-browser fingerprint without --enable-automation.
        wd = await _webdriver(port)
        assert not wd, f"navigator.webdriver should be falsy under stealth, got {wd!r}"

        # 2. Discovery works via the registry (not getBrowserCommandLine, which
        #    is empty under stealth). This is the backbone of zero-port CLI use.
        guid = _query_chrome_guid(port)
        assert registry.lookup(port, guid) is not None, "instance not registered"
        assert any(p == port for p, _pid in find_workspace_chromes()), (
            "stealth Chrome not found by find_workspace_chromes — registry path "
            "regressed; zero-`--port` tools would fail to locate it"
        )
        assert any(b["port"] == port for b in browser_list()["browsers"])

        # 3. Under stealth the CDP command line is unreadable (the premise of the
        #    whole registry rework) — asserting it keeps that assumption honest.
        assert not _query_chrome_cmdline(port), (
            "getBrowserCommandLine returned args under stealth — --enable-"
            "automation leaked back in; the registry would be unnecessary"
        )
    finally:
        browser_stop(port=port)
        assert registry.lookup(port, _query_chrome_guid(port)) is None


@pytest.mark.asyncio
async def test_stealth_false_restores_automation_flags():
    result = browser_start(headless=True, temp=True, stealth=False, reuse="none")
    assert "error" not in result, result
    port = result["port"]
    try:
        cmdline = _query_chrome_cmdline(port)
        assert cmdline, "stealth=False must keep --enable-automation (readable cmdline)"
        assert any("enable-automation" in a for a in cmdline), (
            f"stealth=False must emit --enable-automation; got {cmdline!r}"
        )
        # webdriver is still masked (that is what AutomationControlled does).
        assert not await _webdriver(port)
    finally:
        browser_stop(port=port)
