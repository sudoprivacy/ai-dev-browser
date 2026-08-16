"""`--tab-url` / `url_contains` must match the URL's scheme+host+path before its
query string, so a substring buried in an OAuth `redirect_uri=` param can't
hijack tab selection to the wrong tab.

Reported on a government SPA login flow: selecting the working tab by a path
fragment picked the OAuth/redirect tab instead, because that tab's URL carried
the same fragment inside `?redirect_uri=...`. A full-URL substring match is
ambiguous exactly there; matching the path first resolves it, with a full-URL
fallback so an intentional query-param selector still works.
"""

from __future__ import annotations

import asyncio
import contextlib
import http.server
import os
import threading

import pytest

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


class _OkHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<title>ok</title>ok")

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _OkHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()


@pytest.fixture
def port():
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    try:
        yield port
    finally:
        browser_stop(port=port)


async def _open(browser, url):
    await browser.get(url)
    await asyncio.sleep(0.4)


async def test_prefers_path_over_redirect_uri_query(server, port):
    """The reported bug: the token is in one tab's PATH and another tab's
    `redirect_uri=` query. Selection must land on the path tab."""
    browser = await connect_browser(port=port)
    try:
        # Open the OAuth/redirect tab FIRST so a naive first-substring match
        # would pick it, then the real page.
        await _open(
            browser,
            f"http://127.0.0.1:{server}/oauth?redirect_uri=http://app/declare-form",
        )
        await _open(browser, f"http://127.0.0.1:{server}/declare-form")

        tab = await get_active_tab(browser, url_contains="declare-form")
        path = tab._target.url.split("?", 1)[0]
        assert path.endswith("/declare-form"), (
            f"selection should prefer the path tab, got {tab._target.url}"
        )
    finally:
        with contextlib.suppress(Exception):
            await browser.close()


async def test_query_only_match_still_selects(server, port):
    """Fallback: when the substring matches nothing in any path but does appear
    in a query param, that tab is still selectable (backward-compatible)."""
    browser = await connect_browser(port=port)
    try:
        await _open(browser, f"http://127.0.0.1:{server}/home")
        await _open(browser, f"http://127.0.0.1:{server}/callback?state=xyz-token-abc")

        tab = await get_active_tab(browser, url_contains="xyz-token-abc")
        assert "xyz-token-abc" in tab._target.url, (
            f"query-only selector should still match as a fallback: {tab._target.url}"
        )
    finally:
        with contextlib.suppress(Exception):
            await browser.close()
