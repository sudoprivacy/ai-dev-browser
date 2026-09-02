"""click_by_* now resolves the real clickable ancestor, verifies, and falls back.

Reproduces the reporter's framework-managed UI: a Material-style option whose
click handler is on the CONTAINER's pointerdown (text leaf inside), and a target
hidden behind an overlay so the trusted click can't reach it (exercising the
synthetic-dispatch fallback). Launches a real headless Chrome (E2E).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib

import pytest

from ai_dev_browser.core import connect_browser, get_active_tab
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.elements import click_by_text

_HTML = """<!doctype html><meta charset=utf-8><body>
<div id="opt" jsaction="x" role="button"
     style="height:55px;padding:15px;cursor:pointer;background:#eee">
  <span id="lbl">Get a verification code</span>
</div>
<button id="plain" onclick="document.title='PLAIN'">Use another account</button>
<ul style="list-style:none;padding:0;margin:0">
  <li id="li" style="width:460px;height:55px;line-height:55px;background:#ddd;cursor:default">
    <span>Get a code from the app</span>
  </li>
</ul>
<div id="lires">no</div>
<div style="position:relative;height:40px;width:320px;margin-top:8px">
  <button id="covered" style="position:absolute;inset:0"
    onclick="document.getElementById('cres').textContent='covered-clicked'">Send it another way</button>
  <div id="cover" style="position:absolute;inset:0;z-index:5"></div>
</div>
<div id="inert" style="width:200px;height:30px">Inert label</div>
<div id="result">none</div>
<div id="cres">no</div>
<script>
  // Handler on the CONTAINER's pointerdown — a text-leaf coordinate click that
  // resolves to the leaf's thin box would miss it.
  document.getElementById('opt').addEventListener('pointerdown', function () {
    document.getElementById('result').textContent = 'selected';
    document.title = 'SELECTED';
  });
  // Reporter's FR-A shape: sized <li>, handler via addEventListener, NO
  // role/jsaction/onclick attribute, cursor NOT pointer.
  document.getElementById('li').addEventListener('click', function () {
    document.getElementById('lires').textContent = 'li-clicked';
  });
</script></body>"""


@pytest.fixture
async def tab():
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    browser = None
    try:
        browser = await connect_browser(port=port)
        the_tab = await get_active_tab(browser)
        url = "data:text/html;base64," + base64.b64encode(_HTML.encode()).decode()
        await the_tab.get(url)
        await asyncio.sleep(0.3)
        yield the_tab
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


@pytest.mark.asyncio
async def test_click_resolves_container_and_fires_pointerdown_handler(tab):
    res = await click_by_text(tab, "Get a verification code")
    marker = await tab.evaluate("document.getElementById('result').textContent")
    assert marker == "selected", "container pointerdown handler must fire"
    assert res.get("verified") is True, res
    assert res.get("target") == "div", (
        "must resolve the clickable container, not the leaf"
    )


@pytest.mark.asyncio
async def test_click_falls_back_to_synthetic_when_trusted_is_blocked(tab):
    # The trusted click at the button's centre lands on the overlay; the fallback
    # dispatches events directly on the resolved element.
    res = await click_by_text(tab, "Send it another way")
    cres = await tab.evaluate("document.getElementById('cres').textContent")
    assert cres == "covered-clicked", "fallback must reach the covered handler"
    assert res.get("verified") is True, res
    assert res.get("method") in ("synthetic", "js_click"), res


@pytest.mark.asyncio
async def test_sized_element_with_no_clickable_attribute_still_clicks(tab):
    # FR-A: a sized, visible element whose handler is addEventListener'd (no
    # role/jsaction/onclick) must still get a full click — never clicked:False.
    res = await click_by_text(tab, "Get a code from the app")
    fired = await tab.evaluate("document.getElementById('lires').textContent")
    assert res.get("clicked") is True, res
    assert res.get("verified") is True, res
    assert fired == "li-clicked", "addEventListener handler must fire"


@pytest.mark.asyncio
async def test_plain_button_still_verifies(tab):
    res = await click_by_text(tab, "Use another account")
    assert res.get("verified") is True and res.get("method") == "trusted", res
    assert (await tab.evaluate("document.title")) == "PLAIN"


@pytest.mark.asyncio
async def test_os_click_engaged_only_when_opted_in(tab, monkeypatch):
    # OS input can't be exercised for real in CI (it moves the machine's cursor),
    # so mock it: an inert element makes every CDP rung fail verification, so the
    # OS rung is the only thing left — and it must fire ONLY when opted in.
    import ai_dev_browser.core.ax as ax

    calls = []

    async def fake_os_click(t, el):
        calls.append(1)
        return False  # dispatched but (mock) no effect

    monkeypatch.setattr(ax, "_os_click", fake_os_click)
    monkeypatch.setattr(ax, "_pyautogui_available", lambda: False)

    off = await click_by_text(tab, "Inert label", os_click=False)
    assert calls == [], "OS rung must NOT run when opted out"
    assert off.get("verified") is False

    on = await click_by_text(tab, "Inert label", os_click=True)
    assert calls == [1], "OS rung must run as the last resort when opted in"
    assert "hint" in on and "osinput" in on["hint"], on
