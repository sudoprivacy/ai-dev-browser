"""Locator workflows introduced in v0.5.1.

Real user journeys the previous toolbox couldn't express:

- Cross-frame html-id lookup (`find_by_html_id` / `click_by_html_id`):
  lis8 insurance system case — LLM needed to click an element with a known
  html id that lived inside an iframe. The accessibility tree didn't surface
  it, so LLM fell back to multi-line cross-frame JS. v0.5.1 gives it a direct
  CLI tool.

- XPath queries (`find_by_xpath` / `click_by_xpath`): cases the AX tree
  can't express cleanly — e.g. "the 3rd div inside .results with a specific
  data-attr". Previously required raw js_evaluate.

- Navigation feedback on click (`click_by_text` / `click_by_ref`): LLM used
  to have no signal whether a click caused navigation, so it chained
  screenshot + page_discover to verify. v0.5.1 returns
  `{navigated, url_before, url_after, title_after}` inline.

- `AI_DEV_BROWSER_OUTPUT_DIR` env var: consumers (sudowork, etc.) inject a
  persistent output directory; LLM doesn't have to learn scratch/persistent
  conventions per host.
"""

import base64
import os
from pathlib import Path

import pytest

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, get_active_tab
from ai_dev_browser.core.elements import (
    click_by_html_id,
    click_by_text,
    click_by_xpath,
    find_by_html_id,
    find_by_xpath,
)
from ai_dev_browser.core.navigation import page_goto
from ai_dev_browser.core.page import page_screenshot


SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


@pytest.fixture
async def tab():
    result = browser_start(headless=True, temp=True)
    assert "error" not in result
    port = result["port"]
    try:
        browser = await connect_browser(port=port)
        yield await get_active_tab(browser)
    finally:
        browser_stop(port=port)


def _data_url(html: str) -> str:
    return "data:text/html;base64," + base64.b64encode(html.encode()).decode()


# ---------------------------------------------------------------------------
# find_by_html_id / click_by_html_id — cross-frame html id lookup
# ---------------------------------------------------------------------------


async def test_find_by_html_id_in_top_document(tab):
    """Real scenario: LLM knows a rendered template has id=submit-btn,
    wants to verify it exists before clicking.

    Workflow: goto page with known id → find_by_html_id → verify fields →
    click_by_html_id → observe state change
    """
    html = """
    <html><body>
      <button id="submit-btn" onclick="document.body.dataset.clicked='yes'">Submit</button>
      <div id="status">idle</div>
    </body></html>
    """
    await page_goto(tab, _data_url(html))

    found = await find_by_html_id(tab, "submit-btn")
    assert found["found"] is True
    assert found["tag"] == "button"
    assert "Submit" in found["text"]
    assert found["visible"] is True

    result = await click_by_html_id(tab, "submit-btn")
    assert result["clicked"] is True
    assert result["html_id"] == "submit-btn"

    # Click caused a side effect we can observe — proves the helper hit
    # the real element, not a decoy
    confirmation = await tab.evaluate(
        "document.body.dataset.clicked", return_by_value=True
    )
    assert confirmation == "yes"


async def test_find_by_html_id_recurses_into_same_origin_iframe(tab):
    """Real scenario: lis8 insurance system case reproduced.

    The menu button lives inside a nested iframe. Accessibility tree lookup
    from the top document doesn't reach it. Previously LLM wrote multi-line
    recursive JS; now it's one CLI call.

    Workflow: load page → JS-create a same-origin iframe with a button →
    find_by_html_id reaches into it → click_by_html_id fires the button →
    verify iframe-internal state changed
    """
    # Use a same-origin iframe created via JS (about:blank inherits parent
    # origin). Avoids the data:URL + srcdoc cross-origin trap.
    await page_goto(tab, _data_url("<html><body><h1>Host</h1></body></html>"))
    setup = """
    new Promise(r => {
      const ifr = document.createElement('iframe');
      ifr.id = 'outer';
      document.body.appendChild(ifr);
      ifr.onload = () => {
        ifr.contentDocument.body.innerHTML =
          '<button id="menu-item" ' +
          'onclick="document.body.dataset.clicked=\\'menu\\'">New Order</button>';
        r(true);
      };
      ifr.src = 'about:blank';
    })
    """
    await tab.evaluate(setup, await_promise=True, return_by_value=True)

    # AX-tree-based tools typically miss dynamically-added iframe contents;
    # prove we find the button anyway via cross-frame recursion.
    found = await find_by_html_id(tab, "menu-item")
    assert found["found"] is True, f"Expected to find iframe-nested id, got {found}"
    assert found["tag"] == "button"

    result = await click_by_html_id(tab, "menu-item")
    assert result["clicked"] is True

    # Verify click landed inside the iframe's own document, not on a ghost
    inner_state = await tab.evaluate(
        "document.getElementById('outer').contentDocument.body.dataset.clicked"
    )
    assert inner_state == "menu"


async def test_find_by_html_id_returns_not_found_for_missing(tab):
    """Existence-check use case: LLM wants to know if an id is on the page
    before committing to an action path."""
    await page_goto(tab, _data_url("<html><body><h1>Nothing here</h1></body></html>"))

    result = await find_by_html_id(tab, "does-not-exist")
    assert result == {"found": False}

    click_result = await click_by_html_id(tab, "does-not-exist")
    assert click_result["clicked"] is False
    assert click_result["error"] == "not found"


# ---------------------------------------------------------------------------
# find_by_xpath / click_by_xpath — queries the AX tree can't express
# ---------------------------------------------------------------------------


async def test_click_by_xpath_uses_complex_predicate(tab):
    """Real scenario: page has multiple similar buttons, only the one with a
    specific data-attr should fire. AX tree / text match can't express this;
    XPath can.

    Workflow: load page with ambiguous buttons → click_by_xpath with
    predicate → verify only the targeted one fired
    """
    html = """
    <html><body>
      <button data-role="cancel" onclick="window.__fired='cancel'">OK</button>
      <button data-role="confirm" onclick="window.__fired='confirm'">OK</button>
      <button data-role="other" onclick="window.__fired='other'">OK</button>
    </body></html>
    """
    await page_goto(tab, _data_url(html))

    result = await click_by_xpath(tab, "//button[@data-role='confirm']")
    assert result["clicked"] is True

    fired = await tab.evaluate("window.__fired", return_by_value=True)
    assert fired == "confirm", f"Expected the role=confirm button, got {fired}"


async def test_find_by_xpath_returns_element_info(tab):
    """LLM uses XPath to locate + inspect; doesn't need a ref, just info."""
    html = """
    <html><body>
      <div class="result" data-score="42">match</div>
      <div class="result" data-score="7">other</div>
    </body></html>
    """
    await page_goto(tab, _data_url(html))

    found = await find_by_xpath(tab, "//div[@data-score='42']")
    assert found["found"] is True
    assert found["tag"] == "div"
    assert found["text"] == "match"


# ---------------------------------------------------------------------------
# Navigation feedback on click — eliminates screenshot+discover probe
# ---------------------------------------------------------------------------


async def test_click_by_text_reports_navigation(tab):
    """Real scenario: LLM clicks a link, wants to know the resulting URL
    without doing a separate screenshot + page_discover probe.

    Workflow: goto page with link → click_by_text → inspect returned dict
    → URL after matches link target, navigated=True
    """
    start = _data_url(
        "<html><body><a href='https://example.com/'>Example</a></body></html>"
    )
    await page_goto(tab, start)

    result = await click_by_text(tab, text="Example")
    assert result["clicked"] is True
    assert result["navigated"] is True
    assert result["url_before"] == start
    assert result["url_after"].startswith("https://example.com")


async def test_click_by_text_reports_no_navigation_on_in_page_click(tab):
    """Same mechanism but verifies we don't false-report navigation for
    clicks that don't change URL (toggle, dropdown, in-page button)."""
    html = """
    <html><body>
      <button id="t" onclick="this.textContent='toggled'">Toggle</button>
    </body></html>
    """
    start = _data_url(html)
    await page_goto(tab, start)

    result = await click_by_text(tab, text="Toggle")
    assert result["clicked"] is True
    assert result["navigated"] is False
    assert result["url_after"] == start


# ---------------------------------------------------------------------------
# AI_DEV_BROWSER_OUTPUT_DIR — consumer-injected persistent output path
# ---------------------------------------------------------------------------


async def test_screenshot_honors_output_dir_env_var(tab, tmp_path, monkeypatch):
    """Real scenario: sudowork gateway sets AI_DEV_BROWSER_OUTPUT_DIR to the
    workspace root so screenshots taken without explicit --path land in a
    persistent location (no scratch/mv dance).

    Workflow: set env var → goto page → page_screenshot (no path) → saved
    file is under the env-var directory, not ./screenshots/
    """
    monkeypatch.setenv("AI_DEV_BROWSER_OUTPUT_DIR", str(tmp_path))
    await page_goto(tab, _data_url("<html><body><h1>Hi</h1></body></html>"))

    result = await page_screenshot(tab=tab)
    saved = Path(result["path"])
    assert saved.exists()
    # Resolved to handle drive-letter / short-name differences on Windows
    assert saved.resolve().is_relative_to(tmp_path.resolve()), (
        f"{saved} is not under env-var dir {tmp_path}"
    )
    assert saved.suffix == ".png"
    assert saved.stat().st_size > 0

    # Cleanup created file so test leaves no artifacts
    saved.unlink()


async def test_screenshot_falls_back_to_default_dir_without_env(
    tab, tmp_path, monkeypatch
):
    """No env var → fall back to ./screenshots/ as before (backward compat)."""
    monkeypatch.delenv("AI_DEV_BROWSER_OUTPUT_DIR", raising=False)
    # Redirect cwd to tmp to avoid polluting the real repo
    monkeypatch.chdir(tmp_path)
    await page_goto(tab, _data_url("<html><body><h1>Hi</h1></body></html>"))

    result = await page_screenshot(tab=tab)
    saved = Path(result["path"])
    assert saved.exists()
    assert "screenshots" in saved.parts
    saved.unlink()
