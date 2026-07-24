"""`select_text` produces a real text Selection over on-page text, including
text inside a *same-origin* iframe — the case a synthetic `mouse_drag` cannot
do (DevTools-synthesized mouse events don't drive Blink's cross-frame selection
state machine, and a same-origin iframe has no separate CDP target to route
frame-local input to).

Like `test_text_locator`, the iframe fixture is served over `http://127.0.0.1`
on purpose: `file://` and `data:` iframes are *opaque* ("null") origins, so a
fixture built from either would silently exercise the cross-origin path and
prove nothing about same-origin support.
"""

from __future__ import annotations

import functools
import http.server
import os
import threading

import pytest

from ai_dev_browser._cli import wrap_core
from ai_dev_browser.core import page_goto, select_text
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, get_active_tab

SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)

INDEX_HTML = """<!doctype html><title>sel</title><body>
<p id="para">Alpha bravo charlie delta echo foxtrot</p>
<p id="rich">Prefix <b>BOLD</b> and <i>ITALIC</i> suffix here</p>
<iframe src="frame.html" width="320" height="80"></iframe>
</body>"""

FRAME_HTML = (
    "<!doctype html><body><p id=fp>Frame selectable content sentence here</p></body>"
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


async def _top_selection(tab) -> str:
    return await tab.evaluate("window.getSelection().toString()")


async def _iframe_selection(tab) -> str:
    return await tab.evaluate(
        "document.querySelector('iframe').contentWindow.getSelection().toString()"
    )


async def test_selects_text_in_top_frame(tab):
    result = await select_text(tab, "bravo charlie")

    assert result["selected"] is True
    assert result["frame"] == "top"
    assert result["text"] == "bravo charlie"
    assert result["collapsed"] is False
    # The selection is real and persists — a separate read still sees it.
    assert await _top_selection(tab) == "bravo charlie"


async def test_selects_text_in_same_origin_iframe(tab):
    """The reported bug: a coordinate drag selects nothing inside the iframe.
    `select_text` builds the Range in the iframe's own document instead."""
    result = await select_text(tab, "selectable content")

    assert result["selected"] is True
    assert result["frame"] == "iframe"
    assert result["text"] == "selectable content"
    # Populated in the iframe's Selection, and nothing bleeds into the parent.
    assert await _iframe_selection(tab) == "selectable content"
    assert await _top_selection(tab) == ""


async def test_to_text_spans_multiple_elements(tab):
    """`to_text` extends the selection across intervening elements — a run a
    single-text-node substring match can't express."""
    result = await select_text(tab, "Prefix", to_text="suffix")

    assert result["selected"] is True
    # Spanned the <b> and <i> between the anchor and focus text nodes.
    assert "BOLD" in result["text"]
    assert "ITALIC" in result["text"]
    assert result["chars"] > len("Prefix")


async def test_miss_reports_not_selected(tab):
    result = await select_text(tab, "no such text present zzz")

    assert result["selected"] is False
    assert result["text"] == "no such text present zzz"


async def test_wrapped_tool_injects_failure_hint(tab):
    """Rule 5b: a failing tool return carries the `Failure:` docstring text as
    `hint`, so the recovery guidance reaches the caller at failure time."""
    wrapped = wrap_core(select_text, "selected")
    out = await wrapped(tab, "definitely-absent-string-qqq")

    assert out["selected"] is False
    assert "hint" in out
    assert "same-origin iframe" in out["hint"]


async def test_selection_change_event_fires(tab):
    """The one event the primitive fires is `selectionchange`; a listener in the
    top document observes the change."""
    await tab.evaluate(
        "window.__sc = 0; document.addEventListener('selectionchange', "
        "() => { window.__sc++; })"
    )
    await select_text(tab, "delta echo")
    assert await tab.evaluate("window.__sc") >= 1
