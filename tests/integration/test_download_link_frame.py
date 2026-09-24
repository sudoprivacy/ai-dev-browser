"""download_link reaches a control inside a cross-origin / sandboxed iframe.

The requesting consumer's shape: a download anchor inside a
`sandbox="allow-scripts allow-downloads"` srcdoc iframe (an opaque-origin
OOPIF). A bare XPath only searches the main frame; `frame=` runs the locate +
trusted click inside the OOPIF's session, and the download behavior is armed on
that session too so the completion event is actually seen. Launches a real
headless Chrome.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib

import pytest

from ai_dev_browser.core import connect_browser, get_active_tab
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.download import download_link

_VCARD = (
    "data:text/vcard;charset=utf-8,BEGIN:VCARD%0AVERSION:3.0%0AFN:Sandbox%0AEND:VCARD"
)
_INNER = f'<a id="vcf" download="s.vcf" href="{_VCARD}" style="display:block;padding:30px">Download</a>'
_OUTER = (
    "<!doctype html><meta charset=utf-8><body>"
    '<iframe sandbox="allow-scripts allow-downloads" srcdoc="'
    + _INNER.replace('"', "&quot;")
    + '" style="width:400px;height:200px;border:0"></iframe></body>'
)


@pytest.fixture
async def tab():
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, result
    port = result["port"]
    browser = None
    try:
        browser = await connect_browser(port=port)
        the_tab = await get_active_tab(browser)
        url = "data:text/html;base64," + base64.b64encode(_OUTER.encode()).decode()
        await the_tab.get(url)
        await asyncio.sleep(0.4)
        yield the_tab
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


@pytest.mark.asyncio
async def test_bare_xpath_cannot_reach_into_the_sandbox(tab, tmp_path):
    res = await download_link(
        tab, xpath='//a[@id="vcf"]', download_dir=str(tmp_path), timeout=6
    )
    assert res.get("downloaded") is False, res
    assert res.get("error") == "not found", res  # main-frame search only


@pytest.mark.asyncio
async def test_frame_downloads_from_inside_the_sandbox(tab, tmp_path):
    res = await download_link(
        tab,
        xpath='//a[@id="vcf"]',
        download_dir=str(tmp_path),
        timeout=10,
        frame="srcdoc",
    )
    assert res.get("downloaded") is True, res
    assert res.get("filename") == "s.vcf", res
    assert (tmp_path / "s.vcf").exists(), list(tmp_path.iterdir())
