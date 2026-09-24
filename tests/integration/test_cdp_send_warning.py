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


@pytest.mark.asyncio
async def test_array_of_objects_param_is_reachable(tab):
    # setEmulatedMedia's `features` is a list of typed objects — cdp_send used to
    # blow up ("'dict' has no attribute 'to_json'"); now it coerces + applies.
    async def dark():
        return await tab.evaluate("matchMedia('(prefers-color-scheme: dark)').matches")

    res = await cdp_send(
        tab,
        "Emulation.setEmulatedMedia",
        json.dumps({"features": [{"name": "prefers-color-scheme", "value": "light"}]}),
    )
    assert "error" not in res, res
    assert await dark() is False, "forcing light must take effect"
    await cdp_send(
        tab,
        "Emulation.setEmulatedMedia",
        json.dumps({"features": [{"name": "prefers-color-scheme", "value": "dark"}]}),
    )
    assert await dark() is True, "forcing dark must take effect"
