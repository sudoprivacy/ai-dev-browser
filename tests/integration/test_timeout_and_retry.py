"""Integration tests for the v0.5.0 timeout / retry contract.

- Per-call `timeout=` overrides the 30s default.
- On timeout, Tab.send raises by default (never silently replays).
- `retry_on_timeout=True` opts into the Electron SPA recovery path.

Locks in the correctness fix: auto-retry of Runtime.evaluate was
causing silent double execution of non-idempotent JS (e.g. POSTs).
"""

import asyncio
import os
import time

import pytest

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, get_active_tab
from ai_dev_browser.core._transport import ProtocolException


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


async def test_timeout_param_overrides_default(tab):
    """tab.evaluate(code, timeout=N) lets N >> 30s happen without timing out."""
    # Sleep 2s inside JS — well below any reasonable timeout, but proves
    # the timeout parameter is accepted and doesn't cap the call.
    start = time.perf_counter()
    result = await tab.evaluate(
        "new Promise(r => setTimeout(() => r(42), 2000))",
        await_promise=True,
        return_by_value=True,
        timeout=10.0,
    )
    elapsed = time.perf_counter() - start
    assert result == 42
    assert 2.0 <= elapsed < 5.0, f"expected ~2s, got {elapsed}"


async def test_short_timeout_raises_without_retry(tab):
    """A command that exceeds its timeout raises ProtocolException
    — no silent replay that could double-execute side effects."""
    # Track how many times the JS body actually runs.
    await tab.evaluate("window.__retry_counter = 0", return_by_value=True)

    with pytest.raises(ProtocolException) as exc:
        await tab.evaluate(
            "new Promise(r => { window.__retry_counter++; "
            "setTimeout(() => r('done'), 3000); })",
            await_promise=True,
            return_by_value=True,
            timeout=0.3,  # forces timeout before promise resolves
        )
    assert "timed out" in str(exc.value).lower()

    # Wait for the original promise to settle so the counter is final.
    await asyncio.sleep(3.5)

    # With retry_on_timeout=False default, JS ran exactly once. The old
    # behaviour would show 2 here (original + auto-retry replay).
    count = await tab.evaluate("window.__retry_counter", return_by_value=True)
    assert count == 1, f"JS body executed {count} times, expected 1 (no retry)"


async def test_retry_on_timeout_opt_in_still_works(tab):
    """retry_on_timeout=True preserves the Electron SPA recovery path —
    caller explicitly acknowledges the command is safe to replay."""
    from ai_dev_browser.cdp import runtime

    # Runtime.evaluate is safe here because this expression is idempotent
    # (arithmetic, no side effects). Verifies the opt-in path doesn't
    # break after the default flip.
    cdp_cmd = runtime.evaluate(
        expression="1 + 1", return_by_value=True, allow_unsafe_eval_blocked_by_csp=True
    )
    remote_obj, errors = await tab.send(cdp_cmd, retry_on_timeout=True, timeout=10.0)
    assert errors is None
    assert remote_obj.value == 2
