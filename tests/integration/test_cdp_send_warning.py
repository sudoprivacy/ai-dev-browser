"""cdp_send attaches a warning for a session-scoped effect (issue #7, E2E).

The command still executes and returns its result; the point is the added
`warning` so a caller no longer reads `{"result": null}` from
Browser.setDownloadBehavior as a lasting redirect. Launches a real headless
Chrome.
"""

from __future__ import annotations

import contextlib
import json
import tempfile

import pytest

from ai_dev_browser.core import connect_browser, get_active_tab
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.cdp import cdp_send


@pytest.fixture
async def tab():
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, result
    port = result["port"]
    browser = None
    try:
        browser = await connect_browser(port=port)
        yield await get_active_tab(browser)
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


@pytest.mark.asyncio
async def test_set_download_behavior_carries_persistence_warning(tab):
    res = await cdp_send(
        tab,
        "Browser.setDownloadBehavior",
        json.dumps({"behavior": "allow", "downloadPath": tempfile.gettempdir()}),
    )
    # the command executed (result present) AND the drop is no longer silent
    assert "result" in res, res
    assert "warning" in res, res
    assert "does NOT persist" in res["warning"]
    assert "download_link" in res["warning"]


@pytest.mark.asyncio
async def test_benign_method_has_no_warning(tab):
    res = await cdp_send(tab, "Browser.getVersion")
    assert "result" in res and "warning" not in res, res
