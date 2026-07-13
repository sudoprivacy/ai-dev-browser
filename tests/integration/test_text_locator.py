"""Every `*_by_text` tool locates an element the same way.

`click_by_text` used to run `DOM.performSearch` while `find_by_text` walked the
accessibility tree. Two sibling tools that both claim to find "the element
labelled X", answering differently:

    <button><Icon/><span>Sudo</span> <span>Code</span></button>

`DOM.performSearch` matches *within a single text node*, and no single text node
here contains "Sudo Code" — so `click_by_text` returned not-found while
`find_by_text` (accessible name: "Sudo Code") found it fine. React componentry
produces this shape constantly.

Both now route through `_ax_by_text`, so they cannot disagree. `performSearch`
stays as a tier-2 fallback for what the AX tree never exposes, which keeps every
locator that worked before working.

The iframe cases need a real HTTP origin: `file://` and `data:` iframes are
*opaque* ("null") origins, so a fixture built from either silently exercises the
cross-origin path and proves nothing about same-origin support.
"""

from __future__ import annotations

import functools
import http.server
import os
import threading

import pytest

from ai_dev_browser.core import (
    click_by_text,
    find_by_text,
    js_evaluate,
    page_goto,
    type_by_text,
)
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, get_active_tab

SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)

INDEX_HTML = """<!doctype html><title>t0</title><body>
<button id="icon-btn" onclick="document.title='ICON'">
  <svg width="12" height="12"></svg><span>Remote Agent</span>
</button>

<button id="split-btn" onclick="document.title='SPLIT'">
  <svg width="12" height="12"></svg>
  <span><span>Sudo</span> <span>Code</span></span>
  <span>NEW</span><span>x</span><span>y</span>
</button>

<div id="div-menu" onclick="document.title='DIV'">Divvy Menu</div>

<input id="search" type="text" placeholder="Search products...">
<button id="search-btn" onclick="document.title='SEARCH'">Search</button>

<label for="email">Email</label><input id="email">

<iframe src="frame.html" width="300" height="60"></iframe>
</body>"""

FRAME_HTML = (
    "<button id=fb onclick=\"parent.document.title='IFRAME'\">Inside Frame</button>"
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


@pytest.fixture
def site(tmp_path):
    """Serve the fixture over http://127.0.0.1 so the iframe is same-origin."""
    (tmp_path / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (tmp_path / "frame.html").write_text(FRAME_HTML, encoding="utf-8")

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(tmp_path)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    finally:
        server.shutdown()


@pytest.fixture
async def tab(site):
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    try:
        browser = await connect_browser(port=port)
        the_tab = await get_active_tab(browser)
        await page_goto(the_tab, site)
        yield the_tab
    finally:
        browser_stop(port=port)


async def _title(tab) -> str:
    return await tab.evaluate("document.title")


@pytest.mark.parametrize(
    "text,expected_title,shape",
    [
        ("Remote Agent", "ICON", "icon sibling + <span> label"),
        ("Sudo Code", "SPLIT", "label split across two <span> children"),
        ("Divvy Menu", "DIV", "<div onclick> — Chrome reports it as StaticText"),
        ("Inside Frame", "IFRAME", "button inside a same-origin iframe"),
    ],
)
async def test_click_by_text_handles_composed_labels(tab, text, expected_title, shape):
    result = await click_by_text(tab, text, timeout=5)
    assert result["clicked"] is True, f"{shape}: not clicked"
    assert await _title(tab) == expected_title, f"{shape}: handler never fired"


@pytest.mark.parametrize("text", ["Sudo Code", "Inside Frame"])
async def test_find_and_click_agree_on_the_same_element(tab, text):
    """The property that makes the two tools siblings rather than rivals."""
    found = await find_by_text(tab, text)
    clicked = await click_by_text(tab, text, timeout=5)

    assert found["found"] is True
    assert clicked["clicked"] is True
    assert found["ref"] == clicked["ref"]


async def test_ambiguous_text_picks_the_exact_match(tab):
    """`page_discover`'s text filter is a case-insensitive *substring* test
    returning matches in tree order, so "Search" also matches the
    `<input placeholder="Search products...">` that sits above the button.
    Taking the first hit would type-focus the box instead of clicking Search."""
    result = await click_by_text(tab, "Search", timeout=5)

    assert result["clicked"] is True
    assert await _title(tab) == "SEARCH", "clicked the input, not the button"


async def test_type_by_text_lands_in_the_input_not_its_label(tab):
    """`<label for=email>` resolves onto the input's accessible name, so the
    label is the natural way to name the field. The DOM text search this tool
    used to run matched the <label> element itself."""
    result = await type_by_text(tab, name="Email", text="a@b.com", timeout=5)

    assert result["typed"] is True
    value = await js_evaluate(tab, "document.querySelector('#email').value")
    assert value["result"] == "a@b.com"
