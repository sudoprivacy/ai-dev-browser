"""`js_evaluate(frame=...)` runs an expression INSIDE a cross-origin iframe
(an OOPIF), which the top document — and every same-origin tool built on it
(`find_by_text`, `click_by_text`, `page_discover`) — physically cannot reach.

Reported by a downstream integrator on 全国电子税务局: a tax form lives inside a
cross-origin `<iframe>`, and `find_by_text` / `click_by_text` / `js_evaluate`
all failed with "Cross-origin iframes are not scanned" because the OOPIF is a
*separate* CDP target with its own DOM the top session can't see.

The fixture builds a REAL out-of-process iframe hermetically: one local server
answers two fake sites (`parent.test`, `child.test`) via `--host-resolver-rules`,
so `parent.test` embedding `child.test` is genuinely cross-site and Chrome
splits the child into its own target. `--proxy-server=direct://` keeps the
fake hostnames off any system proxy. (A different *port* would be cross-origin
but same-*site* — Chrome would keep it in-process and no OOPIF would form, so
the port trick can't exercise this path.)

  * top scan (`find_by_text`)          → blind to the child      (the bug)
  * `js_evaluate(frame="child.test")`  → reads + mutates the child (the fix)
  * `js_evaluate(frame="nope")`        → loud error listing the real frames
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import os
import threading

import pytest

from ai_dev_browser._cli import wrap_core
from ai_dev_browser.core import find_by_text, js_evaluate, page_goto
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, get_active_tab

SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)

FRAME_HTML = (
    "<!doctype html><meta charset=utf-8><body>"
    "<h1 id=fh>CHILD-FRAME-HEADING</h1>"
    "<input id=taxid aria-label=纳税人识别号>"
    "</body>"
)

# {port} is filled in once the ephemeral server port is known.
INDEX_HTML = (
    "<!doctype html><meta charset=utf-8><body>"
    "<h1 id=top>PARENT-TOP-HEADING</h1>"
    '<iframe src="http://child.test:{port}/frame.html" width=320 height=120></iframe>'
    "</body>"
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


@pytest.fixture
def site(tmp_path):
    """One local server, two fake sites — a genuine cross-site (OOPIF) embed."""
    (tmp_path / "frame.html").write_text(FRAME_HTML, encoding="utf-8")
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(tmp_path)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    (tmp_path / "index.html").write_text(INDEX_HTML.format(port=port), encoding="utf-8")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://parent.test:{port}/index.html"
    finally:
        server.shutdown()


@pytest.fixture
async def tab(site):
    result = browser_start(
        headless=True,
        temp=True,
        reuse="none",
        # Map the fake sites to the local server, and keep them off any system
        # proxy so the direct 127.0.0.1 connection succeeds.
        extra_args=[
            "--host-resolver-rules=MAP *.test 127.0.0.1",
            "--proxy-server=direct://",
        ],
    )
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    browser = None
    try:
        browser = await connect_browser(port=port)
        the_tab = await get_active_tab(browser)
        await page_goto(the_tab, site)
        # The OOPIF loads over a second HTTP round-trip after the parent's load
        # event; give it a beat to become an attachable target.
        await asyncio.sleep(1.5)
        yield the_tab
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        browser_stop(port=port)


async def test_top_scan_is_blind_to_cross_origin_frame(tab):
    """The reported bug, pinned: the top document's text scan cannot see content
    that lives inside the cross-origin child — so `find_by_text` misses it."""
    # Sanity: the top scan DOES see top-level content.
    top_hit = await find_by_text(tab, "PARENT-TOP-HEADING")
    assert top_hit.get("found"), f"top scan should see the parent: {top_hit}"

    # But it is blind to the OOPIF's content — exactly the reporter's wall.
    child_hit = await find_by_text(tab, "CHILD-FRAME-HEADING")
    assert not child_hit.get("found"), (
        "top scan must NOT reach cross-origin frame content — if it does, the "
        "fixture isn't a real OOPIF and the whole test proves nothing"
    )


async def test_frame_reads_inside_the_oopif(tab):
    """`js_evaluate(frame="child.test")` evaluates in the child's own document,
    so `document` is the frame's document and its content is reachable."""
    res = await js_evaluate(
        tab, "document.getElementById('fh').innerText", frame="child.test"
    )
    assert res["result"] == "CHILD-FRAME-HEADING", res
    # `document` really is the child's — its URL is the frame's, not the parent's.
    href = await js_evaluate(tab, "document.location.href", frame="child.test")
    assert "child.test" in href["result"] and "frame.html" in href["result"], href


async def test_frame_side_effect_mutates_only_the_child(tab):
    """The integrator's actual need: fill a form field that lives inside the
    cross-origin iframe. The write lands in the child and does not leak to the
    parent (which has no such element)."""
    await js_evaluate(
        tab,
        "document.getElementById('taxid').value = '91110000MA00'",
        frame="child.test",
    )
    got = await js_evaluate(
        tab, "document.getElementById('taxid').value", frame="child.test"
    )
    assert got["result"] == "91110000MA00", got

    # The parent document has no #taxid — the mutation was frame-local.
    parent = await js_evaluate(tab, "!!document.getElementById('taxid')")
    assert parent["result"] is False, "the field must not exist in the parent doc"


async def test_frame_matches_by_url_substring(tab):
    """`frame` matches any URL substring — the caller need not know the exact
    target id, just enough of the URL to disambiguate."""
    res = await js_evaluate(
        tab, "document.getElementById('fh').innerText", frame="frame.html"
    )
    assert res["result"] == "CHILD-FRAME-HEADING", res


async def test_frame_is_attached_once_and_cached(tab):
    """The flat-session attach is cached per frame — a second frame eval reuses
    the session rather than re-attaching (the resolver is the SSOT for it)."""
    assert tab._frame_sessions == {}, "no frames attached before first use"
    await js_evaluate(tab, "1", frame="child.test")
    assert len(tab._frame_sessions) == 1, "first frame eval must attach + cache"
    cached = dict(tab._frame_sessions)
    await js_evaluate(tab, "2", frame="child.test")
    assert tab._frame_sessions == cached, "second eval must reuse the cached session"


async def test_no_match_fails_loud_and_lists_available_frames(tab):
    """A frame that doesn't match must fail loud AND enumerate the real
    cross-origin frames, so the caller immediately knows what to pass —
    routed through the CLI wrapper so the error-envelope + hint path is real."""
    wrapped = wrap_core(js_evaluate, "result")
    out = await wrapped(tab, "1", frame="definitely-not-a-frame-zzz")

    assert "error" in out, out
    assert "no cross-origin iframe target matching" in out["error"]
    # The available frame is named in the error, so a retry is obvious.
    assert "child.test" in out["error"], (
        f"error should list the real frames to retry against: {out['error']}"
    )
