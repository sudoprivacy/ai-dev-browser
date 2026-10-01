#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-01 13:09:26

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 2/2 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Launch -> open Wikipedia -> locate search -> type real keys -> click submit without movement -> wait for article -> inspect and capture
  ✅ Open Wikipedia -> scroll to language menu -> trusted click -> verify expansion -> restart worker -> reacquire button -> collapse -> inspect and capture

Uncovered workflows: None
"""

# Standard library imports
import os
from pathlib import Path

# Third-party imports
import pytest

# Skill-specific imports
# Source: tests/integration/scenarios_public_web.json (integration-test-generator)
import json
import asyncio
import time
from urllib.parse import urlparse
from ai_dev_browser.core import (
    cdp_send,
    js_evaluate,
    mouse_click,
    page_goto,
    page_screenshot,
    page_wait_element,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("AI_DEV_BROWSER_LIVE_WEB") != "1",
    reason="Set AI_DEV_BROWSER_LIVE_WEB=1 to access public websites",
)

# Integration guard: push users to set env vars, allow CI to opt-out
SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)
REQUIRED_ENV = ["AI_DEV_BROWSER_TEST_EXTENSION_CHROME"]


@pytest.fixture(autouse=True)
def _integration_guard():
    """Skip if SKIP_INTEGRATION is set, fail if required env vars are missing."""
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set — skipping integration tests")
    missing = [v for v in REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        pytest.fail(
            f"Missing env vars: {', '.join(missing)}. "
            f"Set them to run integration tests, or set SKIP_INTEGRATION=1 to skip."
        )


def test_public_web_cli_search_and_read_article(cli, cli_browser, tmp_path):
    """
    Real scenario: Use the CLI to search Wikipedia and open the matching article

    Workflow: Launch -> open Wikipedia -> locate search -> type real keys -> click submit without movement -> wait for article -> inspect and capture

    User problem: An agent must be able to use headless mode and no-move clicks on a public website through independent CLI processes, then verify the destination page.

    Data flow:
      1. Launch a fresh browser and open the public search page
      2. Type the query into the discovered search input using keyboard events
      3. Submit with no-move and wait for the article to become visible
      4. Save the observed article and screenshot for visual review
    """
    # Step 1: Launch a fresh browser and open the public search page
    port = cli_browser()
    navigation = cli("page_goto", "--port", port, "--url", "https://www.wikipedia.org/")
    assert (
        navigation["url"] == "https://www.wikipedia.org/"
        and navigation["title"] == "Wikipedia"
    ), navigation
    search = cli("page_wait_element", "--port", port, "--selector", "#searchInput")
    assert search["found"] and search["ref"], search

    # Step 2: Type the query into the discovered search input using keyboard events
    typed = cli(
        "type_by_ref",
        "--port",
        port,
        "--ref",
        search["ref"],
        "--text",
        "Google Chrome",
        "--clear",
        "--keystrokes",
    )
    assert (
        typed["typed"] and typed["verified"] and typed["methods_tried"][0] == "keys"
    ), typed
    location = cli(
        "js_evaluate",
        "--port",
        port,
        "--expression",
        "(() => { const e=document.querySelector('button[type=submit]'); e.scrollIntoView({block:'center'}); const r=e.getBoundingClientRect(); const x=r.x+r.width/2,y=r.y+r.height/2; return {x,y,hit:e.contains(document.elementFromPoint(x,y)),query:document.getElementById('searchInput').value}; })()",
    )["result"]
    assert location["hit"] and location["query"] == "Google Chrome", location

    # Step 3: Submit with no-move and wait for the article to become visible
    clicked = cli(
        "mouse_click",
        "--port",
        port,
        "--x",
        location["x"],
        "--y",
        location["y"],
        "--no-move",
    )
    assert clicked == {"clicked": True}, clicked
    article = cli(
        "page_wait_element",
        "--port",
        port,
        "--selector",
        "#firstHeading",
        "--timeout",
        "45",
    )
    assert article["found"], article
    deadline = time.monotonic() + 45
    while True:
        state = cli(
            "js_evaluate",
            "--port",
            port,
            "--expression",
            "({url:location.href,title:document.title,ready:document.readyState,heading:document.getElementById('firstHeading')?.innerText,text:document.getElementById('mw-content-text')?.innerText.slice(0,400) || ''})",
        )["result"]
        if state["ready"] == "complete" and "Chrome" in state["text"]:
            break
        assert time.monotonic() < deadline, state
        time.sleep(0.2)
    destination = urlparse(state["url"])
    assert (
        destination.hostname.endswith(".wikipedia.org")
        and destination.path == "/wiki/Google_Chrome"
    ), state
    assert (
        "Google Chrome" in state["heading"]
        and "Google Chrome" in state["title"]
        and "Chrome" in state["text"]
    ), state

    # Step 4: Save the observed article and screenshot for visual review
    shot = cli(
        "page_screenshot",
        "--port",
        port,
        "--path",
        str(tmp_path / "wikipedia-article.png"),
    )
    assert Path(shot["path"]).is_file() and Path(shot["path"]).stat().st_size > 1000, (
        shot
    )
    (tmp_path / "evidence.json").write_text(
        json.dumps(
            {
                "navigation": navigation,
                "typed": typed,
                "clicked": clicked,
                "article": state,
                "screenshot": shot,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def test_public_web_extension_menu_survives_worker_restart(
    live_extension, tmp_path
):
    """
    Real scenario: Use the real extension to expand a public site's menu and continue after worker restart

    Workflow: Open Wikipedia -> scroll to language menu -> trusted click -> verify expansion -> restart worker -> reacquire button -> collapse -> inspect and capture

    User problem: An extension driver must deliver trusted clicks to visible controls on a public site, and recover the same tab and page state after its worker restarts.

    Data flow:
      1. Open Wikipedia through the real extension and identify the owned tab
      2. Scroll the control into view and confirm the click will hit it
      3. Restart the worker and verify the same tab and expanded page survive
      4. Reacquire the current coordinates and use another trusted click to collapse the menu
    """
    # Step 1: Open Wikipedia through the real extension and identify the owned tab
    navigation = await live_extension.call(page_goto, url="https://www.wikipedia.org/")
    assert (
        navigation["url"] == "https://www.wikipedia.org/"
        and navigation["title"] == "Wikipedia"
    ), navigation
    before = (await live_extension.call(cdp_send, method="AiDevBrowser.debugState"))[
        "result"
    ]
    assert before["mainTabId"] in before["attached"], before
    # Activate only our isolated automation tab so Chrome advances UI animations.
    await live_extension.call(
        cdp_send,
        method="Target.activateTarget",
        params=json.dumps({"targetId": str(before["mainTabId"])}),
    )
    assert (
        await live_extension.call(js_evaluate, expression="document.visibilityState")
    )["result"] == "visible"
    button = await live_extension.call(
        page_wait_element, selector="#js-lang-list-button"
    )
    assert button["found"], button

    # Step 2: Scroll the control into view and confirm the click will hit it
    locate = "(() => { const e=document.getElementById('js-lang-list-button'); e.scrollIntoView({block:'center'}); const r=e.getBoundingClientRect(); const x=r.x+r.width/2,y=r.y+r.height/2; return {x,y,width:innerWidth,height:innerHeight,hit:e.contains(document.elementFromPoint(x,y)),expanded:e.getAttribute('aria-expanded')}; })()"
    await live_extension.call(
        js_evaluate,
        expression="(() => { window.acceptanceClicks=[]; document.getElementById('js-lang-list-button').addEventListener('click', e => window.acceptanceClicks.push(e.isTrusted)); })()",
    )
    location = (await live_extension.call(js_evaluate, expression=locate))["result"]
    assert (
        location["expanded"] == "false"
        and location["hit"]
        and 0 < location["x"] < location["width"]
        and 0 < location["y"] < location["height"]
    ), location
    assert (
        await live_extension.call(
            mouse_click, x=location["x"], y=location["y"], move=False
        )
        is True
    )
    inspect_state = "({url:location.href,title:document.title,expanded:document.getElementById('js-lang-list-button').getAttribute('aria-expanded'),clicks:window.acceptanceClicks})"
    expanded = (await live_extension.call(js_evaluate, expression=inspect_state))[
        "result"
    ]
    assert expanded["expanded"] == "true" and expanded["clicks"] == [True], expanded
    # The site keeps a 1000s visibility transition alive; wait for its visual size/transform transitions.
    deadline = time.monotonic() + 10
    while True:
        animations = (
            await live_extension.call(
                js_evaluate,
                expression="document.getAnimations().filter(a => a.playState === 'running' && a.transitionProperty !== 'visibility').length",
            )
        )["result"]
        if animations == 0:
            break
        assert time.monotonic() < deadline, "Menu animation did not settle"
        await asyncio.sleep(0.05)
    shot = await live_extension.call(
        page_screenshot, path=str(tmp_path / "wikipedia-expanded.png")
    )
    assert Path(shot["path"]).is_file() and Path(shot["path"]).stat().st_size > 1000, (
        shot
    )

    # Step 3: Restart the worker and verify the same tab and expanded page survive
    await live_extension.restart_worker()
    after = (await live_extension.call(cdp_send, method="AiDevBrowser.debugState"))[
        "result"
    ]
    assert (
        after["mainTabId"] == before["mainTabId"]
        and after["autoTabs"] == before["autoTabs"]
        and after["mainTabId"] in after["attached"]
    ), (before, after)
    recovered = (await live_extension.call(js_evaluate, expression=inspect_state))[
        "result"
    ]
    assert recovered == expanded, (expanded, recovered)

    # Step 4: Reacquire the current coordinates and use another trusted click to collapse the menu
    location = (await live_extension.call(js_evaluate, expression=locate))["result"]
    assert location["hit"] and location["expanded"] == "true", location
    assert (
        await live_extension.call(
            mouse_click, x=location["x"], y=location["y"], move=False
        )
        is True
    )
    collapsed = (await live_extension.call(js_evaluate, expression=inspect_state))[
        "result"
    ]
    assert (
        collapsed["expanded"] == "false"
        and collapsed["clicks"] == [True, True]
        and collapsed["url"] == expanded["url"]
    ), collapsed
    # The site keeps a 1000s visibility transition alive; wait for its visual size/transform transitions.
    deadline = time.monotonic() + 10
    while True:
        animations = (
            await live_extension.call(
                js_evaluate,
                expression="document.getAnimations().filter(a => a.playState === 'running' && a.transitionProperty !== 'visibility').length",
            )
        )["result"]
        if animations == 0:
            break
        assert time.monotonic() < deadline, "Menu animation did not settle"
        await asyncio.sleep(0.05)
    shot = await live_extension.call(
        page_screenshot, path=str(tmp_path / "wikipedia-collapsed.png")
    )
    assert Path(shot["path"]).is_file() and Path(shot["path"]).stat().st_size > 1000, (
        shot
    )
    (tmp_path / "evidence.json").write_text(
        json.dumps(
            {
                "before": before,
                "expanded": expanded,
                "afterRestart": after,
                "collapsed": collapsed,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert cdp_send is not None
