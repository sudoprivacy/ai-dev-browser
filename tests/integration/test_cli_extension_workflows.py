#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-01 02:10:42

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 2/2 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Invalid launch mode -> correct mode -> navigate -> locate -> no-move click -> verify UI and stdout -> close
  ✅ Connect -> inspect extension -> navigate -> trusted click -> screenshot -> stop/start worker -> reconnect -> verify same tab and UI

Uncovered workflows: None
"""

# Standard library imports
import os
from pathlib import Path

# Third-party imports
import pytest

# Skill-specific imports
# Source: tests/integration/scenarios_cli_extension.json (integration-test-generator)
from ai_dev_browser.core import (
    cdp_send,
    js_evaluate,
    mouse_click,
    page_goto,
    page_screenshot,
)

# Integration guard: allow CI to opt-out with SKIP_INTEGRATION=1
SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    """Skip if SKIP_INTEGRATION is set."""
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set — skipping integration tests")


def test_cli_headless_no_move_and_error_output(cli, cli_browser, click_page, tmp_path):
    """
    Real scenario: Start headless, click a visible control without moving, verify trusted input and stdout

    Workflow: Invalid launch mode -> correct mode -> navigate -> locate -> no-move click -> verify UI and stdout -> close

    User problem: An agent must be able to launch with boolean or named headless modes and observe the result of --no-move in a fresh CLI process, including failures.

    Data flow:
      1. inline code operation
      2. inline code operation
      3. inline code operation
      4. inline code operation
      5. inline code operation
    """
    # Step 1: Execute operation
    failure = cli("browser_start", "--headless", "not-a-mode", exit_code=2)
    assert failure["error_code"] == "validation" and failure["retryable"] is False
    assert "headless must be" in failure["error"] and "port" not in failure
    port = cli_browser()
    navigation = cli("page_goto", "--port", port, "--url", click_page)
    assert navigation["url"] == click_page, navigation

    # Step 2: Execute operation
    location = cli(
        "js_evaluate",
        "--port",
        port,
        "--expression",
        "(() => { const r=document.getElementById('action').getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()",
    )["result"]
    assert location["x"] > 0 and location["y"] > 0
    coords = ["--x", location["x"], "--y", location["y"]]

    # Step 3: Execute operation
    clicked = cli("mouse_click", "--port", port, *coords, "--no-move")
    assert clicked == {"clicked": True}, clicked
    state = cli(
        "js_evaluate",
        "--port",
        port,
        "--expression",
        "({clicks:window.clicks,text:document.getElementById('result').textContent})",
    )["result"]
    assert len(state["clicks"]) == 1 and state["clicks"][0]["trusted"] is True, state
    assert state["text"] == "Clicked 1 (trusted=true)", state
    assert cli("mouse_click", "--port", port, *coords, "--no-move", "--human-like") == {
        "clicked": True
    }
    human_state = cli("js_evaluate", "--port", port, "--expression", "window.clicks")[
        "result"
    ]
    assert len(human_state) == 2 and all(event["trusted"] for event in human_state), (
        human_state
    )

    # Step 4: Execute operation
    shot = cli(
        "page_screenshot", "--port", port, "--path", str(tmp_path / "cli-click.png")
    )
    assert Path(shot["path"]).is_file() and Path(shot["path"]).stat().st_size > 1000
    failure = cli(
        "mouse_click",
        "--port",
        port,
        *coords,
        "--no-move",
        "--button",
        "invalid",
        exit_code=1,
    )
    assert isinstance(failure["error"], str) and failure["retryable"] is False, failure
    assert failure["hint"]
    after = cli("js_evaluate", "--port", port, "--expression", "window.clicks.length")[
        "result"
    ]
    assert after == 2, after

    # Step 5: Execute operation
    bad_params = cli(
        "cdp_send",
        "--port",
        port,
        "--method",
        "Runtime.evaluate",
        "--params",
        "[]",
        exit_code=2,
    )
    assert bad_params["error_code"] == "validation"
    unknown = cli(
        "cdp_send",
        "--port",
        port,
        "--method",
        "UnboundDomain.missingMethod",
        exit_code=1,
    )
    assert (
        "missingMethod" in unknown["error"]
        and "has no attribute" not in unknown["error"]
    ), unknown


async def test_real_extension_routing_diagnostics_and_worker_restart(
    live_extension, click_page, tmp_path
):
    """
    Real scenario: Drive a real extension across independent calls and a forced worker restart

    Workflow: Connect -> inspect extension -> navigate -> trusted click -> screenshot -> stop/start worker -> reconnect -> verify same tab and UI

    User problem: Browser-level discovery can succeed while page routing loses the target ID. The extension must drive the correct tab on legacy and asyncio WebSockets and recover its owned tabs after a worker restart.

    Data flow:
      1. inline code operation
      2. inline code operation
      3. inline code operation
      4. inline code operation
    """
    # Step 1: Execute operation
    before = (await live_extension.call(cdp_send, method="AiDevBrowser.debugState"))[
        "result"
    ]
    assert len(before["autoTabs"]) == 1 and before["mainTabId"] in before["attached"], (
        before
    )

    # Step 2: Execute operation
    navigation = await live_extension.call(page_goto, url=click_page)
    assert navigation["url"] == click_page, navigation
    location = (
        await live_extension.call(
            js_evaluate,
            expression="(() => { const r=document.getElementById('action').getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()",
        )
    )["result"]

    # Step 3: Execute operation
    assert (
        await live_extension.call(
            mouse_click, x=location["x"], y=location["y"], move=False
        )
        is True
    )
    state = (await live_extension.call(js_evaluate, expression="window.clicks"))[
        "result"
    ]
    assert len(state) == 1 and state[0]["trusted"] is True, state
    shot = await live_extension.call(
        page_screenshot, path=str(tmp_path / "extension-click.png")
    )
    assert Path(shot["path"]).is_file() and Path(shot["path"]).stat().st_size > 1000

    # Step 4: Execute operation
    await live_extension.restart_worker()
    after = (await live_extension.call(cdp_send, method="AiDevBrowser.debugState"))[
        "result"
    ]
    assert (
        after["mainTabId"] == before["mainTabId"]
        and after["autoTabs"] == before["autoTabs"]
    ), (before, after)
    assert after["mainTabId"] in after["attached"], after
    state = (
        await live_extension.call(
            js_evaluate,
            expression="({count:window.clicks.length,text:document.getElementById('result').textContent})",
        )
    )["result"]
    assert state == {"count": 1, "text": "Clicked 1 (trusted=true)"}, state
    assert (
        await live_extension.call(
            mouse_click, x=location["x"], y=location["y"], move=False
        )
        is True
    )
    assert (await live_extension.call(js_evaluate, expression="window.clicks.length"))[
        "result"
    ] == 2


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert cdp_send is not None
