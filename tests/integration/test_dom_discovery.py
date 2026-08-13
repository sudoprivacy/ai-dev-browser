"""Regression: DOM-based discovery for ARIA-less enterprise UIs (Kingdee
K3Cloud and friends) + `click_row_by_text`.

K3Cloud builds controls from bare `<div class="kd-*">` + custom
`datarole="..."` attributes with NO standard ARIA, and grids whose rows are
`div[class*=row]` (not `<tr>`, no `role=row`). `Accessibility.getFullAXTree`
can't see them, so `page_discover` returned too few refs and the agent had to
eyeball `mouse_click --x --y`, mis-clicking the neighbouring row.

The fixture reproduces that shape exactly (verified against the live Kingdee
session on port 9460: same-origin, no canvas/iframe, datarole inputs, div
grid). Tests pin:
  * DOM discovery surfaces the ARIA-less inputs + rows the AX tree misses,
    with a `ref` + `box`,
  * `page_discover` stays READ-ONLY (never mutates the page),
  * `click_row_by_text` hits the row that actually contains the text — not the
    adjacent one (the reporter's worst pain).
"""

from __future__ import annotations

import base64
import contextlib
import os

import pytest

from ai_dev_browser.core import click_row_by_text, page_discover, page_goto
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


# datarole inputs (no role/label) + a div grid whose rows have NO role=row —
# the exact ARIA-less shape getFullAXTree can't see. Rows record which one was
# clicked / double-clicked so we can prove we hit the right one.
_FIXTURE = """<!DOCTYPE html><html><body style="margin:0;font-family:sans-serif">
<input datarole="username" style="width:220px;height:26px">
<input datarole="password" type="password" style="width:220px;height:26px">
<div class="kd-grid" id="grid"></div>
<div id="log"></div>
<script>
  window.__click = null; window.__dbl = null;
  const rows = [
    ['FIN_READONLY', '财务只读'],
    ['FIN_READWRITE', '财务读写'],
    ['BOS08', '系统管理员'],
    ['HR_ADMIN', '人事管理'],
  ];
  const grid = document.getElementById('grid');
  for (const [code, name] of rows) {
    const d = document.createElement('div');
    d.className = 'kd-grid-row';
    d.style.cssText = 'height:40px;line-height:40px;padding:0 12px;' +
      'border-bottom:1px solid #ddd;cursor:pointer';
    d.textContent = code + '  ' + name;
    d.addEventListener('click', () => { window.__click = code; });
    d.addEventListener('dblclick', () => { window.__dbl = code; });
    grid.appendChild(d);
  }
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


def _names(elements) -> list[str]:
    return [e.get("name") or "" for e in elements]


async def test_dom_scan_surfaces_aria_less_controls_ax_misses(tab):
    """The core win: dom_scan=True surfaces the datarole inputs + div rows;
    dom_scan=False (AX only) misses them."""
    ax_only = await page_discover(tab, dom_scan=False)
    full = await page_discover(tab, dom_scan=True)

    ax_text = " ".join(_names(ax_only))
    assert "FIN_READONLY" not in ax_text, (
        f"AX tree unexpectedly saw the div row — fixture not ARIA-less: {ax_text}"
    )

    # DOM scan surfaces the ARIA-less row, WITH a usable ref + box.
    row = next((e for e in full if "FIN_READONLY" in (e.get("name") or "")), None)
    assert row is not None, f"dom_scan missed the div row; names={_names(full)}"
    assert row.get("ref") and "#" in row["ref"], f"row has no node-backed ref: {row}"
    assert row.get("box") and row["box"]["right"] > row["box"]["left"], row

    # And the datarole login input.
    uname = next((e for e in full if e.get("datarole") == "username"), None)
    assert uname is not None, f"dom_scan missed the datarole input; {_names(full)}"
    assert uname.get("ref"), uname


async def test_page_discover_is_read_only(tab):
    """page_discover must NOT mutate the page — no leftover marker attribute,
    grid HTML byte-identical before and after."""
    before = await tab.evaluate("document.getElementById('grid').innerHTML")
    await page_discover(tab, dom_scan=True)
    after = await tab.evaluate("document.getElementById('grid').innerHTML")
    assert after == before, "page_discover mutated the grid DOM"

    leftover = await tab.evaluate(
        "document.querySelectorAll('[data-adb-i],[data-adb-ref]').length",
        return_by_value=True,
    )
    assert int(leftover or 0) == 0, "page_discover left a marker attribute behind"


async def test_click_row_by_text_hits_the_right_row_not_adjacent(tab):
    """The reporter's worst pain: estimating coordinates double-clicked the
    WRONG adjacent role. click_row_by_text must land on the row that actually
    contains the text."""
    result = await click_row_by_text(tab, "FIN_READONLY")
    assert result["clicked"] is True, result
    assert "FIN_READONLY" in (result.get("text") or ""), result

    clicked = await tab.evaluate("window.__click", return_by_value=True)
    assert clicked == "FIN_READONLY", (
        f"clicked the wrong row: expected FIN_READONLY, got {clicked!r}"
    )


async def test_click_row_by_text_nth_disambiguates(tab):
    """Two rows contain '财务'; matches reports 2 and nth picks between them."""
    first = await click_row_by_text(tab, "财务")  # 财务
    assert first["clicked"] is True and first["matches"] == 2, first
    assert await tab.evaluate("window.__click", return_by_value=True) == "FIN_READONLY"

    await tab.evaluate("window.__click = null")
    second = await click_row_by_text(tab, "财务", nth=1)
    assert second["clicked"] is True, second
    assert await tab.evaluate("window.__click", return_by_value=True) == "FIN_READWRITE"


async def test_click_row_by_text_double_fires_dblclick(tab):
    """double=True must fire a real dblclick (F7 'double-click to choose')."""
    result = await click_row_by_text(tab, "BOS08", double=True)
    assert result["clicked"] is True and result["double"] is True, result
    assert await tab.evaluate("window.__dbl", return_by_value=True) == "BOS08"


async def test_click_row_by_text_not_found_fails_loud(tab):
    """No matching row → fail loud with a reason, not a silent no-op click."""
    result = await click_row_by_text(tab, "NO_SUCH_ROLE_XYZ")
    assert result["clicked"] is False, result
    assert "no grid row" in result["reason"].lower()


# --- Grid checkbox: the Kingdee / MUI / AntD locked-input + wrapper pattern ---
# The real <input> has onclick="return false" (or is hidden); the actual toggle
# handler lives on a wrapper the input sits inside. Clicking the input is a
# no-op; the wrapper must be clicked. Reproduced faithfully (verified against
# live Kingdee port 9460: input onclick="return false;", data-role=checkbox
# wrapper). The div is wider than the input so its centre misses the input,
# exactly like the real cell.
_CHECKBOX_FIXTURE = """<!DOCTYPE html><html><body style="margin:0">
<table id="grid" style="border-collapse:collapse"></table>
<script>
  const rows = [['财务会计 总账', true], ['财务会计 报表', true], ['无复选框行', false]];
  const grid = document.getElementById('grid');
  rows.forEach(function (pair) {
    const name = pair[0], hasBox = pair[1];
    const tr = document.createElement('tr');
    tr.setAttribute('role', 'row');
    const td1 = document.createElement('td');
    td1.setAttribute('role', 'gridcell');
    td1.style.cssText = 'width:90px;height:34px';
    if (hasBox) {
      const div = document.createElement('div');
      div.setAttribute('data-role', 'checkbox');
      div.className = 'kd-checkbox-div gridCheck';
      div.style.cssText = 'width:70px;height:24px;position:relative;cursor:pointer';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.className = 'gridCheck';
      input.setAttribute('onclick', 'return false;');       // locked like Kingdee
      input.style.cssText = 'position:absolute;left:2px;top:4px';
      div.appendChild(input);
      div.appendChild(document.createElement('label'));
      // Only a click NOT on the locked input toggles it — the wrapper handler.
      div.addEventListener('click', function (e) {
        if (e.target !== input) input.checked = !input.checked;
      });
      td1.appendChild(div);
    }
    tr.appendChild(td1);
    const td2 = document.createElement('td');
    td2.setAttribute('role', 'gridcell');
    td2.textContent = name;
    tr.appendChild(td2);
    grid.appendChild(tr);
  });
</script>
</body></html>"""


@pytest.fixture
async def cb_tab():
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    browser_client = None
    try:
        browser_client = await connect_browser(port=port)
        the_tab = await get_active_tab(browser_client)
        url = (
            "data:text/html;charset=utf-8;base64,"
            + base64.b64encode(_CHECKBOX_FIXTURE.encode()).decode()
        )
        await page_goto(the_tab, url)
        yield the_tab
    finally:
        if browser_client is not None:
            with contextlib.suppress(Exception):
                await browser_client.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


async def _cb_checked(tab, needle: str) -> bool:
    js = (
        "(()=>{const r=[...document.querySelectorAll('tr')]"
        f".find(r=>(r.innerText||'').indexOf({needle!r})!==-1);"
        "const c=r&&r.querySelector('input[type=checkbox]');"
        "return c?c.checked:null;})()"
    )
    return await tab.evaluate(js, return_by_value=True)


async def test_direct_input_click_is_a_noop_then_checkbox_mode_toggles(cb_tab):
    """The reporter's exact bug + fix. A direct click on the locked <input>
    does NOT toggle (onclick=return false); click_row_by_text(checkbox=True),
    which clicks the wrapper, DOES."""
    assert await _cb_checked(cb_tab, "总账") is False

    # Contrast: click the locked input's own centre — must stay unchecked.
    rect = await cb_tab.evaluate(
        "(()=>{const r=[...document.querySelectorAll('tr')]"
        ".find(r=>(r.innerText||'').indexOf('总账')!==-1);"
        "const c=r.querySelector('input');const b=c.getBoundingClientRect();"
        "return {x:Math.round(b.left+b.width/2),y:Math.round(b.top+b.height/2)};})()"
    )
    await cb_tab.mouse_click(rect["x"], rect["y"])
    assert await _cb_checked(cb_tab, "总账") is False, (
        "direct input click toggled — fixture isn't reproducing the locked input"
    )

    # The fix: checkbox mode clicks the wrapper → toggles, and verifies it.
    result = await click_row_by_text(cb_tab, "总账", checkbox=True)
    assert result["clicked"] is True, result
    assert result["was"] is False and result["checked"] is True, result
    assert await _cb_checked(cb_tab, "总账") is True


async def test_checkbox_mode_toggles_back_off(cb_tab):
    """Second checkbox click toggles it back — bidirectional, state verified."""
    on = await click_row_by_text(cb_tab, "报表", checkbox=True)
    assert on["checked"] is True, on
    off = await click_row_by_text(cb_tab, "报表", checkbox=True)
    assert off["was"] is True and off["checked"] is False, off


async def test_page_discover_surfaces_the_checkbox_wrapper(cb_tab):
    """The wrapper div (data-role=checkbox) is surfaced as a checkbox-role,
    clickable ref — not just the locked input."""
    els = await page_discover(cb_tab, dom_scan=True)
    wrapper = next((e for e in els if (e.get("role") or "") == "checkbox"), None)
    assert wrapper is not None, f"no checkbox-role wrapper surfaced: {_names(els)}"
    assert wrapper.get("ref") and wrapper.get("box"), wrapper


async def test_checkbox_mode_on_row_without_checkbox_fails_loud(cb_tab):
    """A matched row with no checkbox → fail loud, don't silent-click the row."""
    result = await click_row_by_text(cb_tab, "无复选框行", checkbox=True)
    assert result["clicked"] is False, result
    assert "no checkbox" in result["reason"].lower()


# --- Scroll into view before clicking (long F7 lists) ---------------------------
# A row scrolled out of a long list has off-screen coordinates; clicking them is
# a no-op (the reporter's silent checked:false on a 78-row F7 popup). The target
# is far down a 120px-tall scroll container, so it starts out of view.
_SCROLL_FIXTURE = """<!DOCTYPE html><html><body style="margin:0">
<div id="list" style="height:120px;overflow:auto;border:1px solid #ccc"></div>
<script>
  var list = document.getElementById('list');
  for (var i = 0; i < 40; i++) {
    var row = document.createElement('div');
    row.className = 'kd-grid-row';
    row.style.cssText = 'height:30px;line-height:30px';
    var div = document.createElement('div');
    div.setAttribute('data-role', 'checkbox');
    div.className = 'kd-checkbox-div gridCheck';
    div.style.cssText = 'width:44px;height:20px;position:relative;' +
      'display:inline-block;cursor:pointer';
    var input = document.createElement('input');
    input.type = 'checkbox';
    input.setAttribute('onclick', 'return false;');
    input.style.cssText = 'position:absolute;left:2px;top:2px';
    div.appendChild(input);
    div.addEventListener('click', (function (inp) {
      return function (e) { if (e.target !== inp) inp.checked = !inp.checked; };
    })(input));
    row.appendChild(div);
    var span = document.createElement('span');
    span.textContent = (i === 30) ? 'TARGET_ROW' : ('row' + i);
    row.appendChild(span);
    list.appendChild(row);
  }
</script>
</body></html>"""


@pytest.fixture
async def scroll_tab():
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    browser_client = None
    try:
        browser_client = await connect_browser(port=port)
        the_tab = await get_active_tab(browser_client)
        url = (
            "data:text/html;base64,"
            + base64.b64encode(_SCROLL_FIXTURE.encode()).decode()
        )
        await page_goto(the_tab, url)
        yield the_tab
    finally:
        if browser_client is not None:
            with contextlib.suppress(Exception):
                await browser_client.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


async def test_click_row_scrolls_target_into_view_before_clicking(scroll_tab):
    """The reporter's silent failure: a row scrolled out of a long F7 list had
    off-screen coords, so --checkbox clicked nothing (checked:false). The fix
    scrolls the target in first — so it both scrolls and toggles."""
    before = await scroll_tab.evaluate(
        "document.getElementById('list').scrollTop", return_by_value=True
    )
    assert float(before or 0) == 0, "list should start unscrolled"

    result = await click_row_by_text(scroll_tab, "TARGET_ROW", checkbox=True)
    assert result["clicked"] is True, result
    assert result["checked"] is True, (
        f"off-screen row not scrolled in before click (silent no-op): {result}"
    )

    after = await scroll_tab.evaluate(
        "document.getElementById('list').scrollTop", return_by_value=True
    )
    assert float(after or 0) > 0, "list did not scroll to bring the target into view"
