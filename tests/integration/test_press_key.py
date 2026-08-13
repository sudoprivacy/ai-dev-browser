"""Regression: `press_key` must send a REAL key event that heavy / legacy JS
frameworks (Kingdee Cloud Star ERP and friends) actually respond to.

Reported by a downstream integrator: on Kingdee's "智能搜索" box, `type_by_ref`
typed the text fine (it uses `Input.insertText`), but nothing submitted —
- a synthetic `KeyboardEvent(Enter)` from js_evaluate was ignored (isTrusted=false), and
- a bare `Input.dispatchKeyEvent(Enter)` was ALSO ignored.

Root cause reproduced here: ERP-grade handlers gate Enter on
`event.keyCode === 13`, and `keyCode` is 0 unless the CDP event carries
`windowsVirtualKeyCode`. Some also listen on `keypress`, which only fires when
the key carries `text`. `press_key` sets both, so the event is
indistinguishable from a real press.

The fixture's keydown handler mirrors that gate exactly, so:
  * `press_key("Enter")`            → keyCode 13 + keypress → SUBMITTED
  * a bare dispatchKeyEvent(Enter)  → keyCode 0  → NOT submitted  (contrast)
  * `type_by_ref(..., enter=True)`  → types then submits in one call
"""

from __future__ import annotations

import base64
import contextlib
import os

import pytest

from ai_dev_browser.core import (
    find_by_text,
    page_goto,
    press_key,
    type_by_ref,
    type_by_text,
)
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


# A search box whose keydown handler gates submit on `keyCode === 13` — the
# legacy-framework pattern that ignores malformed synthetic Enter. aria-label
# "智能搜索" mirrors the reporter's Kingdee box so find_by_text can locate it.
_FIXTURE = """<!DOCTYPE html><html><body style="margin:0">
<input id="q" aria-label="智能搜索" style="width:320px;font-size:20px">
<div id="log"></div>
<script>
  window.__keys = [];
  window.__keypress = null;
  window.__submitted = false;
  window.__keyups = 0;
  const q = document.getElementById('q');
  q.addEventListener('keydown', (e) => {
    window.__keys.push({key: e.key, keyCode: e.keyCode, which: e.which});
    if (e.key === 'Enter' && e.keyCode === 13) {           // ERP-style gate
      window.__submitted = true;
      document.getElementById('log').textContent = 'SUBMITTED:' + q.value;
    }
  });
  q.addEventListener('keypress', (e) => { window.__keypress = e.keyCode; });
  q.addEventListener('keyup', () => { window.__keyups++; });   // live-filter gate
</script>
</body></html>"""


@pytest.fixture
async def tab():
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    browser_client = None
    try:
        browser_client = await connect_browser(port=port)
        the_tab = await get_active_tab(browser_client)
        # charset=utf-8 so Chrome decodes the CJK aria-label ("智能搜索")
        # correctly — without it the bytes are read as latin-1 and the
        # accessible name mojibakes, so find_by_text can't match it.
        url = (
            "data:text/html;charset=utf-8;base64,"
            + base64.b64encode(_FIXTURE.encode()).decode()
        )
        await page_goto(the_tab, url)
        yield the_tab
    finally:
        if browser_client is not None:
            with contextlib.suppress(Exception):
                await browser_client.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


async def _state(tab) -> dict:
    return await tab.evaluate(
        "({keys: window.__keys, keypress: window.__keypress,"
        " submitted: window.__submitted,"
        " value: document.querySelector('#q').value,"
        " log: document.getElementById('log').textContent})"
    )


async def _focus_box(tab) -> None:
    await tab.evaluate("document.querySelector('#q').focus()")


async def _box_ref(tab) -> str:
    hit = await find_by_text(tab, "智能搜索")
    assert hit.get("found"), f"could not locate the search box: {hit}"
    return hit["ref"]


async def test_press_key_enter_fires_real_keycode_and_submits(tab):
    """press_key('Enter') on the focused box must deliver keyCode 13 + a
    keypress, so an ERP-style `keyCode === 13` handler fires — the whole
    point of the fix."""
    await _focus_box(tab)

    result = await press_key(tab, "Enter")
    assert result["pressed"] is True, result
    assert result["key"] == "Enter"

    st = await _state(tab)
    assert st["keys"], "no keydown reached the focused box"
    last = st["keys"][-1]
    assert last["key"] == "Enter"
    assert last["keyCode"] == 13, f"keyCode must be 13, got {last}"
    assert st["keypress"] == 13, (
        f"keypress must fire (text='\\r'), got {st['keypress']}"
    )
    assert st["submitted"] is True, "keyCode-13-gated handler did not fire"


async def test_naive_enter_without_vkey_does_not_submit(tab):
    """Contrast / root-cause pin: a bare dispatchKeyEvent(Enter) WITHOUT a
    virtual key code lands keyCode 0, so the ERP gate stays shut — exactly
    the reporter's failure. If a future 'cleanup' drops windowsVirtualKeyCode
    from press_key, the test above breaks and this one explains why."""
    from ai_dev_browser.cdp import input_ as cdp_input

    await _focus_box(tab)
    # No windows_virtual_key_code / text — the malformed Enter.
    await tab.send(cdp_input.dispatch_key_event("keyDown", key="Enter", code="Enter"))
    await tab.send(cdp_input.dispatch_key_event("keyUp", key="Enter", code="Enter"))

    st = await _state(tab)
    assert st["keys"], "keydown should still reach the box"
    assert st["keys"][-1]["keyCode"] == 0, (
        f"naive Enter should have keyCode 0, got {st['keys'][-1]}"
    )
    assert st["submitted"] is False, (
        "naive Enter must NOT satisfy a keyCode===13 gate — that's the bug"
    )


async def test_type_by_ref_enter_types_and_submits(tab):
    """The one-call ergonomic: type_by_ref(enter=True) lands the text AND
    submits — the reporter's requested 'type_by_ref --enter'."""
    ref = await _box_ref(tab)

    result = await type_by_ref(tab, ref, "widget", enter=True)
    assert result["typed"] is True, result
    assert result["entered"] is True, f"enter=True should press Enter: {result}"

    st = await _state(tab)
    assert st["value"] == "widget", f"text did not land: {st['value']!r}"
    assert st["submitted"] is True, "type_by_ref(enter=True) did not submit"
    assert st["log"] == "SUBMITTED:widget", f"handler saw wrong value: {st['log']!r}"


async def test_type_by_ref_clear_replaces_text(tab):
    """Guard the refactor: type_by_ref(clear=True) still wipes existing text
    before typing — the select-all/backspace now route through the shared
    _dispatch_key (real virtual key codes) instead of a hand-rolled dispatch,
    so a full-replace must still yield only the new value, not a concatenation."""
    ref = await _box_ref(tab)
    await type_by_ref(tab, ref, "OLDVALUE")
    assert (await _state(tab))["value"] == "OLDVALUE"

    await type_by_ref(tab, ref, "NEWVALUE", clear=True)
    assert (await _state(tab))["value"] == "NEWVALUE", "clear did not wipe old text"


async def test_press_key_with_ref_focuses_then_presses(tab):
    """press_key(ref=...) focuses the element first, so it works even when
    nothing is focused (or focus drifted)."""
    ref = await _box_ref(tab)
    await tab.evaluate("if (document.activeElement) document.activeElement.blur()")

    result = await press_key(tab, "Enter", ref=ref)
    assert result["pressed"] is True, result

    st = await _state(tab)
    assert st["submitted"] is True, "press_key(ref) did not focus-then-submit"


async def test_press_key_tab_delivers_keycode_9(tab):
    """Tab is a real key too — must arrive with keyCode 9 (the second key the
    reporter named). Focus traversal itself is Blink's business; we pin the
    event shape."""
    await _focus_box(tab)
    result = await press_key(tab, "Tab")
    assert result["pressed"] is True, result

    st = await _state(tab)
    assert st["keys"], "no keydown captured"
    last = st["keys"][-1]
    assert last["key"] == "Tab" and last["keyCode"] == 9, f"bad Tab event: {last}"


async def test_type_by_ref_keystrokes_fires_real_key_events(tab):
    """A live filter / autocomplete listens on keyup — the default insertText
    fires NONE, so it never triggers; keystrokes=True fires real per-char key
    events (and still lands the value). The Kingdee '快捷过滤' case."""
    ref = await _box_ref(tab)

    # Default (insertText): value lands, but NO keyup → a keyup-gated filter
    # would never fire.
    await type_by_ref(tab, ref, "abc")
    assert await tab.evaluate("window.__keyups", return_by_value=True) == 0, (
        "insertText fired keyup events — contrast is invalid"
    )

    # keystrokes=True: real key events per char (plus one from the clear's
    # Backspace), so the filter fires; value replaced.
    await type_by_ref(tab, ref, "xyz", clear=True, keystrokes=True)
    ups = await tab.evaluate("window.__keyups", return_by_value=True)
    assert ups >= 3, f"keystrokes did not fire per-char keyup: {ups}"
    value = await tab.evaluate(
        "document.querySelector('#q').value", return_by_value=True
    )
    assert value == "xyz", f"keystrokes value wrong: {value!r}"


async def test_type_by_text_enter_submits(tab):
    """Converged capability: type_by_text also submits with enter (parity with
    type_by_ref) — located by label, typed, Enter."""
    result = await type_by_text(tab, "智能搜索", "hello", enter=True)
    assert result["typed"] is True, result
    assert result.get("entered") is True, result
    assert await tab.evaluate("window.__submitted", return_by_value=True) is True


async def test_type_by_text_keystrokes_fires_keyup(tab):
    """Converged: type_by_text also has keystrokes — real key events fire keyup
    for live filters (the default char-events path does not), value lands."""
    await type_by_text(tab, "智能搜索", "xyz", clear=True, keystrokes=True)
    ups = await tab.evaluate("window.__keyups", return_by_value=True)
    assert ups >= 3, f"type_by_text keystrokes fired no keyup: {ups}"
    val = await tab.evaluate("document.querySelector('#q').value", return_by_value=True)
    assert val == "xyz", f"value wrong: {val!r}"


async def test_type_by_ref_human_like_types_value(tab):
    """Converged: type_by_ref also has human_like (humanized typing, parity with
    type_by_text) — the value still lands."""
    ref = await _box_ref(tab)
    await type_by_ref(tab, ref, "hi", human_like=True, clear=True)
    val = await tab.evaluate("document.querySelector('#q').value", return_by_value=True)
    assert val == "hi", f"human_like value wrong: {val!r}"


async def test_press_key_unknown_key_fails_loud(tab):
    """An unsupported key name must fail loud with the supported list, not
    silently dispatch nothing."""
    result = await press_key(tab, "Frobnicate")
    assert result["pressed"] is False, result
    assert "unknown key" in result["reason"].lower()
    assert "enter" in result["reason"].lower(), "reason should list supported keys"
