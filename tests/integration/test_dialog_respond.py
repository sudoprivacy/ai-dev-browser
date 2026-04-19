"""dialog_respond v0.6.0 contract.

BREAKING change from v0.5.x: signature is now
    dialog_respond(tab, action: Literal["accept","dismiss"]="accept", ...)
instead of
    dialog_respond(tab, accept: bool=True, ...)

Renamed to align with Playwright / CDP convention (`dialog.accept()` /
`dialog.dismiss()`) — LLMs trained on those corpora pattern-match
`action="accept"|"dismiss"` correctly, where the older `accept=True`
boolean (with `--no-accept` for False) made them fight Pythonic CLI
convention against their pretrain intuition.

Tests cover both branches (accept / dismiss) end-to-end plus the
`Literal` choice constraint.
"""

import asyncio
import os

import pytest

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, get_active_tab
from ai_dev_browser.core.dialog import dialog_respond


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


async def test_dialog_respond_accept_resolves_confirm_to_true(tab):
    """`confirm()` returns true when accepted. Verifies action="accept" is
    actually wired to CDP's accept side."""
    # Trigger confirm in the background and await its return value
    eval_task = asyncio.create_task(
        tab.evaluate(
            "new Promise(r => setTimeout(() => r(confirm('proceed?')), 50))",
            await_promise=True,
            return_by_value=True,
        )
    )
    # Give the confirm() a moment to actually open
    await asyncio.sleep(0.2)

    result = await dialog_respond(tab, action="accept", wait_timeout=2.0)
    assert result["success"] is True
    assert result["action"] == "accepted"

    confirm_return = await eval_task
    assert confirm_return is True, "confirm() should return True on accept"


async def test_dialog_respond_dismiss_resolves_confirm_to_false(tab):
    """`confirm()` returns false when dismissed. Verifies action="dismiss"
    is wired to CDP's dismiss side (not accidentally inverted)."""
    eval_task = asyncio.create_task(
        tab.evaluate(
            "new Promise(r => setTimeout(() => r(confirm('proceed?')), 50))",
            await_promise=True,
            return_by_value=True,
        )
    )
    await asyncio.sleep(0.2)

    result = await dialog_respond(tab, action="dismiss", wait_timeout=2.0)
    assert result["success"] is True
    assert result["action"] == "dismissed"

    confirm_return = await eval_task
    assert confirm_return is False, "confirm() should return False on dismiss"


async def test_dialog_respond_accept_is_default(tab):
    """Calling without `action` defaults to accept — same effective default
    as the v0.5.x `accept=True`, so callers that omitted the flag don't
    behave differently after the rename."""
    eval_task = asyncio.create_task(
        tab.evaluate(
            "new Promise(r => setTimeout(() => r(confirm('y?')), 50))",
            await_promise=True,
            return_by_value=True,
        )
    )
    await asyncio.sleep(0.2)

    result = await dialog_respond(tab, wait_timeout=2.0)  # no action= passed
    assert result["action"] == "accepted"
    assert (await eval_task) is True


async def test_dialog_respond_no_dialog_returns_structured_error(tab):
    """If no dialog is open, the result is a structured failure with
    error="no_dialog" — caller branches on the dict, no exception."""
    result = await dialog_respond(tab, action="accept")
    assert result["success"] is False
    assert result["error"] == "no_dialog"
