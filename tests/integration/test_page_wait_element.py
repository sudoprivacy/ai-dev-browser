"""Regression: page_wait_element waits for VISIBLE (not merely present) and
returns a ref — the async-render primitive.

Reported on Kingdee K3Cloud (port 9460): clicking the top-bar search mounts an
`<input placeholder="按 ctrl+shift+s…">` that is present in the DOM but 0-size
until its panel renders. The old page_wait_element polled `querySelector !==
null`, so it returned `found:True` instantly on the still-hidden input, and it
handed back no ref — the agent then slept + re-discovered by hand and often got
a stale/empty ref (`typed:false`).

The enhanced version: waits until the element is actually visible + stable
across two polls, and returns `{ref, x, y, box, ...}` so
`click → page_wait_element(selector=…) → type_by_ref(ref)` is one clean chain,
no sleep, no re-discover.
"""

from __future__ import annotations

import base64
import contextlib
import os

import pytest

from ai_dev_browser.core import page_goto, page_wait_element, type_by_ref
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


# #box starts present-but-hidden (display:none), exactly like the Kingdee search
# input. Clicking #trigger reveals it after 500ms — the async-render pattern.
_FIXTURE = """<!DOCTYPE html><html><body style="margin:0">
<button id="trigger">open search</button>
<input id="box" placeholder="search" style="display:none;width:200px;height:26px">
<span class="pick" style="display:none">HIDDEN-A</span>
<span class="pick" style="display:none">HIDDEN-B</span>
<span class="pick">VISIBLE-C</span>
<script>
  document.getElementById('trigger').addEventListener('click', function () {
    setTimeout(function () {
      document.getElementById('box').style.display = 'inline-block';
    }, 500);
  });
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
        url = "data:text/html;base64," + base64.b64encode(_FIXTURE.encode()).decode()
        await page_goto(the_tab, url)
        yield the_tab
    finally:
        if browser_client is not None:
            with contextlib.suppress(Exception):
                await browser_client.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


async def test_wait_times_out_on_present_but_hidden(tab):
    """The core bug: a present-but-hidden element (display:none) must NOT count
    as found — the old presence-only check returned it instantly."""
    result = await page_wait_element(tab, selector="#box", timeout=1)
    assert result["found"] is False, f"hidden element reported found: {result}"
    assert "ref" not in result
    # hint is injected by wrap_core at the CLI layer; core returns `message`.
    assert "not visible" in result.get("message", "")


async def test_wait_returns_visible_ref_after_async_reveal(tab):
    """The fix, end to end: trigger the async reveal, wait, get a usable ref,
    and type into it via that ref — no sleep, no re-discover."""
    await tab.evaluate("document.getElementById('trigger').click()")  # schedules reveal

    result = await page_wait_element(tab, selector="#box", timeout=5)
    assert result["found"] is True, f"never saw the revealed input: {result}"
    assert result.get("ref") and "#" in result["ref"], result
    assert result.get("box") and result["box"]["right"] > result["box"]["left"]
    assert result["elapsed"] >= 0.4, "returned before the 500ms reveal — didn't wait"

    typed = await type_by_ref(tab, result["ref"], "hello")
    assert typed["typed"] is True, typed
    value = await tab.evaluate(
        "document.getElementById('box').value", return_by_value=True
    )
    assert value == "hello", f"the returned ref wasn't usable: value={value!r}"


async def test_wait_picks_first_visible_not_first_match(tab):
    """With several same-class nodes whose leading ones are hidden (a menu/grid
    with 63 same-class links where only some are rendered), the wait must return
    the first VISIBLE one — not querySelector's first (hidden) match."""
    result = await page_wait_element(tab, selector=".pick", timeout=3)
    assert result["found"] is True, result
    assert result["name"] == "VISIBLE-C", f"resolved a hidden sibling: {result}"


async def test_wait_not_found_fails_loud(tab):
    """A selector that never matches → fail loud with a hint, not hang forever
    or silently succeed."""
    result = await page_wait_element(tab, selector="#does-not-exist", timeout=1)
    assert result["found"] is False, result
    assert result.get("message")
