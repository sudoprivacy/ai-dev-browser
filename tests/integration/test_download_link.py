"""`download_link` clicks a download control and waits for the file to land.

The batch-scrape capstone: iterate rows, click each "下载" link, get the saved
path back — no hand-counting the Downloads folder. Unlike `download` (which
needs the file URL), it drives the real control via a TRUSTED scroll-aware
click and captures the browser download via CDP events, so it works for the
POST/session-bound download links common in government / enterprise SPAs.

The fixture serves a page whose link points at an attachment endpoint
(Content-Disposition) 2000px down the page, so both the trusted-scroll click
and the download-event capture are exercised.
"""

from __future__ import annotations

import contextlib
import http.server
import os
import threading

import pytest

from ai_dev_browser.core import download_link, page_goto
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, get_active_tab

SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)

_BODY = b"year,tax\n2025,100\n"


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/file"):
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header(
                "Content-Disposition", 'attachment; filename="report_2025.csv"'
            )
            self.send_header("Content-Length", str(len(_BODY)))
            self.end_headers()
            self.wfile.write(_BODY)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            # Link 2000px down → forces the trusted-scroll path.
            self.wfile.write(
                b"<meta charset=utf-8><div style='height:2000px'>spacer</div>"
                b"<a id=dl href='/file.csv'>download</a>"
            )

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()


@pytest.fixture
async def tab(server):
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    browser = None
    try:
        browser = await connect_browser(port=port)
        the_tab = await get_active_tab(browser)
        await page_goto(the_tab, f"http://127.0.0.1:{server}/page")
        yield the_tab
    finally:
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        browser_stop(port=port)


async def test_download_link_clicks_and_returns_saved_file(tab, tmp_path):
    result = await download_link(
        tab, "//a[@id='dl']", download_dir=str(tmp_path), timeout=15
    )
    assert result["downloaded"] is True, result
    assert result["filename"] == "report_2025.csv", result
    path = result["path"]
    assert path and os.path.exists(path), f"downloaded file missing: {result}"
    assert open(path, "rb").read() == _BODY, "downloaded content mismatch"


async def test_download_link_missing_link_reports_not_found(tab, tmp_path):
    """A bad locator is a clean {downloaded: False} without `clicked` — distinct
    from 'clicked but nothing downloaded'."""
    result = await download_link(
        tab, "//a[@id='nope']", download_dir=str(tmp_path), timeout=5
    )
    assert result["downloaded"] is False, result
    assert "clicked" not in result, f"nothing was clicked: {result}"
    assert "error" in result
