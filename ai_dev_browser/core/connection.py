"""Browser connection utilities.

Provides BrowserClient (CDP client), CookieJar, connect_browser, get_active_tab.
"""

from __future__ import annotations

import asyncio
import json
import logging
import pickle
import re
import urllib.request
from pathlib import Path

from ai_dev_browser.cdp import (
    storage,
    target as cdp_target,
)

from ._tab import Tab
from ._transport import CDPConnection

from .config import DEFAULT_DEBUG_HOST, DEFAULT_DEBUG_PORT

logger = logging.getLogger(__name__)


# =============================================================================
# CookieJar
# =============================================================================


class CookieJar:
    """Cookie management via CDP storage commands.

    Cookie management via CDP storage commands.
    """

    def __init__(self, browser: BrowserClient):
        self._browser = browser

    def _get_connection(self) -> CDPConnection:
        """Get a working connection for cookie operations.

        Uses the browser-level connection (which is always connected).
        Tab connections may not be established yet.
        """
        return self._browser.connection

    async def get_all(self) -> list:
        """Get all browser cookies."""
        conn = self._get_connection()
        return await conn.send(storage.get_cookies(), _is_update=True)

    async def save(self, file: str = ".session.dat", pattern: str = ".*"):
        """Save cookies to file (pickle format).

        Args:
            file: Path to save cookies.
            pattern: Regex pattern to filter cookies.
        """
        cookies = await self.get_all()
        if not cookies:
            return

        pat = re.compile(pattern)
        matched = []
        for cookie in cookies:
            cookie_dict = (
                cookie.to_json() if hasattr(cookie, "to_json") else str(cookie)
            )
            if pat.search(str(cookie_dict)):
                matched.append(cookie)

        path = Path(file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            pickle.dump(matched, fh)
        logger.debug("Saved %d cookies to %s", len(matched), path)

    async def load(self, file: str = ".session.dat", pattern: str = ".*"):
        """Load cookies from file.

        Args:
            file: Path to cookie file.
            pattern: Regex pattern to filter cookies on load.
        """
        path = Path(file)
        if not path.exists():
            logger.debug("Cookie file not found: %s", path)
            return

        try:
            with open(path, "rb") as fh:
                cookies = pickle.load(fh)
        except Exception as e:
            logger.warning("Failed to load cookies from %s: %s", path, e)
            return

        if not cookies:
            return

        pat = re.compile(pattern)
        matched = []
        for cookie in cookies:
            cookie_dict = (
                cookie.to_json() if hasattr(cookie, "to_json") else str(cookie)
            )
            if pat.search(str(cookie_dict)):
                matched.append(cookie)

        if matched:
            conn = self._get_connection()
            await conn.send(storage.set_cookies(matched), _is_update=True)
            logger.debug("Loaded %d cookies from %s", len(matched), path)

    async def clear(self):
        """Clear all browser cookies."""
        conn = self._get_connection()
        await conn.send(storage.clear_cookies(), _is_update=True)


# =============================================================================
# BrowserClient
# =============================================================================


class BrowserClient:
    """CDP browser client.

    Manages the browser-level WebSocket connection, target discovery,
    tab lifecycle, and cookies.
    """

    # Connection cache: reuse existing BrowserClient for same host:port
    _instances: dict[tuple[str, int], "BrowserClient"] = {}

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.targets: list[Tab] = []
        self.connection: CDPConnection | None = None
        self._cookies: CookieJar | None = None

    @classmethod
    async def connect(cls, host: str, port: int) -> BrowserClient:
        """Connect to an existing Chrome instance via CDP.

        Reuses existing connection if one is alive for the same host:port.
        """
        key = (host, port)

        # Reuse existing connection if alive
        existing = cls._instances.get(key)
        if existing and existing.connection and not existing.connection.closed:
            # Refresh target list
            await existing.update_targets()
            return existing

        # Close stale instance if any
        if existing:
            await existing.close()

        instance = cls(host, port)

        # 1. Get WebSocket URL
        ws_url = await instance._get_ws_url()

        # 2. Connect browser-level WebSocket
        instance.connection = CDPConnection(ws_url)
        await instance.connection.connect()

        # 3. Set up target discovery and get initial targets
        await instance.connection.send(
            cdp_target.set_discover_targets(discover=True), _is_update=True
        )
        await instance.update_targets()

        cls._instances[key] = instance
        return instance

    async def close(self):
        """Close all WebSocket connections (browser + tabs)."""
        # Close tab connections
        for tab in self.targets:
            if not tab._connection.closed:
                await tab._connection.disconnect()
        self.targets.clear()

        # Close browser-level connection
        if self.connection and not self.connection.closed:
            await self.connection.disconnect()

        # Remove from cache
        key = (self.host, self.port)
        if BrowserClient._instances.get(key) is self:
            del BrowserClient._instances[key]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def _get_ws_url(self) -> str:
        """Discover WebSocket URL via Chrome HTTP debug API."""
        url = f"http://{self.host}:{self.port}/json/version"
        loop = asyncio.get_running_loop()

        for attempt in range(5):
            try:
                resp = await loop.run_in_executor(None, urllib.request.urlopen, url)
                info = json.loads(resp.read())
                return info["webSocketDebuggerUrl"]
            except Exception:
                if attempt == 4:
                    raise
                await asyncio.sleep(0.5)
        raise ConnectionError(f"Failed to get WebSocket URL from {url}")

    @property
    def tabs(self) -> list[Tab]:
        """Page-type targets only."""
        return [t for t in self.targets if getattr(t._target, "type_", "") == "page"]

    @property
    def main_tab(self) -> Tab | None:
        """First tab."""
        tabs = self.tabs
        return tabs[0] if tabs else None

    @property
    def cookies(self) -> CookieJar:
        if not self._cookies:
            self._cookies = CookieJar(self)
        return self._cookies

    async def get(
        self, url: str = "about:blank", tab_new: bool = False, new_window: bool = False
    ) -> Tab:
        """Open URL in new tab or navigate existing tab."""
        target_id = await self.connection.send(
            cdp_target.create_target(url, new_window=new_window)
        )
        await asyncio.sleep(0.5)
        await self.update_targets()
        # Find the newly created tab
        for t in self.targets:
            if t._target.target_id == target_id:
                return t
        # Fallback: return last tab
        return self.targets[-1] if self.targets else None

    async def update_targets(self):
        """Sync target list with Chrome."""
        result = await self.connection.send(cdp_target.get_targets())
        # result is list[TargetInfo]
        target_infos = result if isinstance(result, list) else [result]
        existing_ids = {t._target.target_id for t in self.targets}

        for info in target_infos:
            tid = info.target_id
            if tid in existing_ids:
                # Update existing target info
                for t in self.targets:
                    if t._target.target_id == tid:
                        t._target = info
                        break
            else:
                # Create new Tab for this target
                ws = f"ws://{self.host}:{self.port}/devtools/page/{tid}"
                tab = Tab(ws, target=info, browser=self)
                self.targets.append(tab)

        # Remove targets that no longer exist (and close their WebSockets)
        current_ids = {info.target_id for info in target_infos}
        kept = []
        for t in self.targets:
            if t._target.target_id in current_ids:
                kept.append(t)
            elif not t._connection.closed:
                await t._connection.disconnect()
        self.targets = kept


# =============================================================================
# Public API (same signatures as before)
# =============================================================================


async def connect_browser(
    host: str = DEFAULT_DEBUG_HOST,
    port: int = DEFAULT_DEBUG_PORT,
) -> BrowserClient:
    """Connect to existing Chrome instance.

    Reuses existing connection for same host:port if alive.
    Supports context manager: async with connect_browser() as browser: ...

    Args:
        host: Chrome debugging host
        port: Chrome debugging port

    Returns:
        BrowserClient instance (also usable as async context manager)

    Raises:
        ConnectionError: If unable to connect
    """
    try:
        browser = await BrowserClient.connect(host=host, port=port)
        await _attach_to_page_targets(browser)
        return browser
    except Exception as e:
        raise ConnectionError(
            f"Failed to connect to Chrome on {host}:{port}: {e}"
        ) from e


async def _attach_to_page_targets(browser: BrowserClient) -> None:
    """Explicitly attach to page targets so Chrome tracks our connection.

    This makes is_chrome_in_use() work reliably: attached=True while
    connected, attached=False when our process exits (WebSocket closes).
    """
    for tab in browser.targets:
        if getattr(tab._target, "type_", "") != "page":
            continue
        tid = tab._target.target_id
        if not tid:
            continue
        try:
            await browser.connection.send(
                cdp_target.attach_to_target(tid, flatten=True), _is_update=True
            )
            logger.debug("Attached to page target %s", tid)
        except Exception as e:
            logger.debug("Could not attach to target %s: %s", tid, e)


async def get_active_tab(browser: BrowserClient) -> Tab:
    """Get the active/main tab from browser.

    Args:
        browser: BrowserClient instance

    Returns:
        Active tab, or creates a blank one if none exists
    """
    page_targets = [
        t for t in browser.targets if getattr(t._target, "type_", "") == "page"
    ]

    for tab in page_targets:
        url = getattr(tab._target, "url", "") or ""
        if url and not url.startswith("about:"):
            return tab

    if page_targets:
        return page_targets[0]

    # No tabs, create one
    return await browser.get("about:blank")
