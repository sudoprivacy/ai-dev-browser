"""type_by_* now VERIFIES the value landed and falls back until it does.

Reproduces the reporter's failure modes with synthetic fields (a field that only
accepts real per-char keys — like Google's 0x0 `#idvPin`; a readonly field; a
field that rejects everything) and asserts the fallback chain + honest
`typed:false` on total failure. Launches a real headless Chrome (E2E).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib

import pytest

from ai_dev_browser.core import connect_browser, get_active_tab
from ai_dev_browser.core.ax import _char_key_spec, _fill_verified
from ai_dev_browser.core.browser import browser_start, browser_stop

_HTML = """<!doctype html><meta charset=utf-8><body>
<input id=normal>
<input id=keysonly>
<input id=locked readonly>
<input id=reject>
<script>
  // keysonly: revert any non-keydown edit to the keydown-accumulated string,
  // so ONLY real per-char keys build the value (Google #idvPin shape).
  const ko = document.getElementById('keysonly');
  let allowed = '';
  ko.addEventListener('keydown', e => { if (e.key && e.key.length === 1) allowed += e.key; });
  ko.addEventListener('input', () => { ko.value = allowed; });
  // reject: wipe on every input — nothing can land.
  const rj = document.getElementById('reject');
  rj.addEventListener('input', () => { rj.value = ''; });
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
async def test_insertext_field_verifies_via_insertext(tab):
    r = await _fill_verified(tab, await tab.select("#normal"), "12345")
    assert r["verified"] and r["method"] == "insertText", r


@pytest.mark.asyncio
async def test_keys_only_field_falls_back_to_keys(tab):
    # insertText is reverted → must fall through to real per-char keys.
    r = await _fill_verified(tab, await tab.select("#keysonly"), "12345")
    assert r["verified"] and r["method"] == "keys", r
    assert r["methods_tried"][:2] == ["insertText", "keys"]


@pytest.mark.asyncio
async def test_readonly_field_falls_back_to_native_setter(tab):
    r = await _fill_verified(tab, await tab.select("#locked"), "12345")
    assert r["verified"] and r["method"] == "native", r


@pytest.mark.asyncio
async def test_total_rejection_reports_honest_failure(tab):
    # The headline fix: a field that never accepts the text reports typed:false,
    # not a false success.
    r = await _fill_verified(tab, await tab.select("#reject"), "12345")
    assert r["typed"] is False and r["verified"] is False, r
    assert r["method"] is None


def test_char_key_spec_populates_code_and_keycode():
    assert _char_key_spec("5") == ("5", "Digit5", 0x35)
    assert _char_key_spec("0") == ("0", "Digit0", 0x30)
    assert _char_key_spec("a") == ("a", "KeyA", 0x41)  # keyCode is the uppercase VK
    assert _char_key_spec("A") == ("A", "KeyA", 0x41)
    assert _char_key_spec("!") == ("!", "", 0)  # falls back; text still drives it
