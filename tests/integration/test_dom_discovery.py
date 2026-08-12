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
