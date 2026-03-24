"""Browser connection utilities.

Provides BrowserClient (CDP client), CookieJar, connect_browser, get_active_tab.
Replaces the previous nodriver-based implementation.
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


class _NodriverUnpickler(pickle.Unpickler):
    """Custom unpickler that redirects nodriver.cdp.* → ai_dev_browser.cdp.*"""

    def find_class(self, module: str, name: str):
        if module.startswith("nodriver.cdp."):
            module = module.replace("nodriver.cdp.", "ai_dev_browser.cdp.", 1)
        return super().find_class(module, name)


class CookieJar:
    """Cookie management via CDP storage commands.

    Compatible with nodriver's pickle-based cookie files.
    """

    def __init__(self, browser: BrowserClient):
        self._browser = browser

    def _get_connection(self) -> CDPConnection:
        """Get a working connection for cookie operations."""
        # Prefer a tab connection (more reliable for cookie scope)
        for tab in self._browser.tabs:
            if not tab.closed:
                return tab._connection
        return self._browser.connection

    async def get_all(self) -> list:
        """Get all browser cookies."""
        conn = self._get_connection()
        return await conn.send(storage.get_cookies())

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
                cookies = _NodriverUnpickler(fh).load()
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
            await conn.send(storage.set_cookies(matched))
            logger.debug("Loaded %d cookies from %s", len(matched), path)

    async def clear(self):
        """Clear all browser cookies."""
        conn = self._get_connection()
        await conn.send(storage.clear_cookies())


# =============================================================================
# BrowserClient
# =============================================================================


class BrowserClient:
    """CDP browser client — replacement for nodriver.Browser.

    Manages the browser-level WebSocket connection, target discovery,
    tab lifecycle, and cookies.
    """

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.targets: list[Tab] = []
        self.connection: CDPConnection | None = None
        self._cookies: CookieJar | None = None

    @classmethod
    async def connect(cls, host: str, port: int) -> BrowserClient:
        """Connect to an existing Chrome instance via CDP.

        1. HTTP GET /json/version → WebSocket URL
        2. Connect browser-level WebSocket
        3. Discover existing targets (tabs)
        """
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

        return instance

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
        self, url: str = "about:blank", new_tab: bool = False, new_window: bool = False
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

        # Remove targets that no longer exist
        current_ids = {info.target_id for info in target_infos}
        self.targets = [t for t in self.targets if t._target.target_id in current_ids]


# =============================================================================
# Public API (same signatures as before)
# =============================================================================


async def connect_browser(
    host: str = DEFAULT_DEBUG_HOST,
    port: int = DEFAULT_DEBUG_PORT,
) -> BrowserClient:
    """Connect to existing Chrome instance.

    Args:
        host: Chrome debugging host
        port: Chrome debugging port

    Returns:
        BrowserClient instance

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
