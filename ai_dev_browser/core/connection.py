"""Browser connection utilities.

Provides BrowserClient (CDP client), CookieJar, connect_browser, get_active_tab.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pickle
import re
import urllib.request
from pathlib import Path

from ai_dev_browser.cdp import (
    browser as cdp_browser,
    network as cdp_network,
    storage,
    target as cdp_target,
)

from ._tab import Tab
from ._transport import CDPConnection

from .config import (
    DEFAULT_DEBUG_HOST,
    DEFAULT_DEBUG_PORT,
    DESKTOP_MIN_WIDTH,
    TAB_URL_ENV,
    resolve_dialog_policy,
    resolve_viewport,
)

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
        """Save cookies to file (JSON format).

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
                matched.append(cookie_dict)

        path = Path(file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(matched, fh, indent=2)
        logger.debug("Saved %d cookies to %s", len(matched), path)

    async def load(self, file: str = ".session.dat", pattern: str = ".*"):
        """Load cookies from file (JSON format, with pickle fallback).

        Args:
            file: Path to cookie file.
            pattern: Regex pattern to filter cookies on load.
        """
        path = Path(file)
        if not path.exists():
            logger.debug("Cookie file not found: %s", path)
            return

        # Try JSON first, fall back to pickle for old files
        cookies = None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            # Convert JSON dicts back to Cookie objects
            cookies = [cdp_network.Cookie.from_json(c) for c in raw]
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError):
            # Fall back to legacy pickle format
            try:
                with open(path, "rb") as fh:
                    cookies = pickle.load(fh)
                logger.debug("Loaded legacy pickle cookies from %s", path)
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
            await conn.send(storage.set_cookies(matched), _is_update=True)  # type: ignore[arg-type]
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


def _resolve_port(port: int | None) -> int:
    """Resolve a Chrome debug port using the same precedence as CLI tools.

    Order: explicit arg → `AI_DEV_BROWSER_PORT` env var → workspace scan
    (find_workspace_chromes) → DEFAULT_DEBUG_PORT as last resort.

    Mirrors `_cli.py` resolution so Python callers that do
    `connect_browser()` without an argument behave the same as
    `python -m ai_dev_browser.tools.<name>` without `--port`.
    """
    if port is not None:
        return port

    import os as _os

    env = _os.environ.get("AI_DEV_BROWSER_PORT")
    if env:
        try:
            return int(env)
        except ValueError:
            pass

    from .port import find_workspace_chromes

    for candidate, _pid in find_workspace_chromes():
        return candidate

    return DEFAULT_DEBUG_PORT


async def connect_browser(
    host: str = DEFAULT_DEBUG_HOST,
    port: int | None = None,
) -> BrowserClient:
    """Connect to an existing Chrome instance.

    Reuses the existing connection for the same host:port if alive.
    Supports context manager: `async with connect_browser() as browser: ...`.

    When `port` is omitted, resolves via the same precedence as CLI
    tools (explicit → `AI_DEV_BROWSER_PORT` env → workspace Chrome
    scan → default). Lets Python scripts start with `browser = await
    connect_browser()` without hard-coding a port — matches the
    zero-arg CLI invocation.

    Args:
        host: Chrome debugging host.
        port: Chrome debugging port. None → auto-detect.

    Returns:
        BrowserClient instance (also usable as async context manager).

    Raises:
        ConnectionError: If unable to connect.
    """
    resolved_port = _resolve_port(port)
    try:
        browser = await BrowserClient.connect(host=host, port=resolved_port)
        return browser
    except Exception as e:
        raise ConnectionError(
            f"Failed to connect to Chrome on {host}:{resolved_port}: {e}"
        ) from e


async def get_active_tab(
    browser: BrowserClient | None = None,
    url_contains: str | None = None,
) -> Tab:
    """Get the tab to act on.

    When `browser` is omitted, auto-connects via `connect_browser()`
    (which itself auto-detects a workspace Chrome port). Lets Python
    scripts collapse `browser = await connect_browser(); tab = await
    get_active_tab(browser)` into a single `tab = await
    get_active_tab()` when they don't need to hold the browser handle.

    **There is no "active tab" in CDP.** Nothing in the protocol reports which
    window has focus, so with more than one page target the choice is a guess:
    the first one whose URL isn't `about:*`, in whatever order the browser
    listed them. On a plain Chrome with one tab that guess is always right. On a
    browser with several page targets — an Electron app with background or
    hidden windows, a Chrome with many tabs — it can land anywhere, and every
    tool in this library then silently acts on the wrong page.

    `url_contains` replaces the guess with a statement. Give it a substring of
    the URL you mean (`":5173"`, `"/checkout"`) and the tab is chosen, not
    inferred. Set `AI_DEV_BROWSER_TAB_URL` to apply it to every call in a
    process without threading the argument through, and every CLI tool takes
    `--tab-url` for the same reason.

    Args:
        browser: BrowserClient instance. None → auto-connect.
        url_contains: Substring the target tab's URL must contain. Falls back to
            `$AI_DEV_BROWSER_TAB_URL`. When it matches nothing, that's an error
            rather than a silent fall-through to the guess — you asked for a
            specific tab, so acting on a different one is never what you wanted.

    Returns:
        The selected tab, or a fresh blank one if the browser has no page target.

    Raises:
        ValueError: `url_contains` was given and no page target matched.
    """
    if browser is None:
        browser = await connect_browser()

    async def _prepared(tab: Tab) -> Tab:
        # Auto-handle JS dialogs FIRST: an open alert/confirm/prompt blocks the
        # render thread, so it would hang the viewport probe below (and every
        # later renderer command). Register the handler for dialogs that open
        # during this session, then clear any that's already showing — the
        # handle command works even while the renderer is blocked. SSOT: the
        # policy lives in resolve_dialog_policy(); None = the consumer opted out
        # (AI_DEV_BROWSER_DIALOG=off) to drive dialogs via dialog_respond.
        from .dialog import _handle_dialog, _setup_auto_dialog_handler

        dialog_policy = resolve_dialog_policy()
        if dialog_policy is not None:
            accept = dialog_policy == "accept"
            try:
                await _setup_auto_dialog_handler(tab, accept=accept)
                await _handle_dialog(tab, accept=accept)
            except Exception:
                pass  # best-effort; never block tab acquisition on dialog setup

        # Give every tab a desktop render viewport so responsive apps don't
        # collapse to mobile layout. SSOT: the size lives in resolve_viewport();
        # None means the consumer opted out (AI_DEV_BROWSER_VIEWPORT=native).
        #
        # Only *establish* it when the tab is currently mobile-width — an
        # already-desktop viewport (our default from a prior command, or an
        # explicit window_set) is left as-is. That keeps the default idempotent,
        # lets desktop-width window_set overrides persist across independent CLI
        # commands, and avoids re-laying-out a heavy page on every call.
        viewport = resolve_viewport()
        if viewport is None:
            return tab
        try:
            current = await tab.evaluate("window.innerWidth", return_by_value=True)
        except Exception:
            current = 0
        if not isinstance(current, (int, float)) or current < DESKTOP_MIN_WIDTH:
            await tab.set_viewport(*viewport)
        return tab

    page_targets = [
        t for t in browser.targets if getattr(t._target, "type_", "") == "page"
    ]

    def _url(tab: Tab) -> str:
        return getattr(tab._target, "url", "") or ""

    def _path_part(u: str) -> str:
        # scheme + host + path, without ?query / #fragment
        return u.split("#", 1)[0].split("?", 1)[0]

    wanted = url_contains or os.environ.get(TAB_URL_ENV) or ""
    if wanted:
        # Prefer a match in the URL's scheme+host+path over one that only hits
        # the query string. Otherwise a substring buried in an OAuth
        # `redirect_uri=` (or any `?...=<target-url>` param) silently hijacks
        # the selection to the login/redirect tab instead of the real page.
        for tab in page_targets:
            if wanted in _path_part(_url(tab)):
                return await _prepared(tab)
        # Fall back to a full-URL substring match so an intentional
        # query-param selector still works when nothing matches the path.
        for tab in page_targets:
            if wanted in _url(tab):
                return await _prepared(tab)
        raise ValueError(
            f"No tab whose URL contains {wanted!r}. Open page targets: "
            f"{[_url(t) for t in page_targets] or 'none'}"
        )

    for tab in page_targets:
        url = _url(tab)
        if url and not url.startswith("about:"):
            return await _prepared(tab)

    if page_targets:
        return await _prepared(page_targets[0])

    # No tabs, create one
    return await _prepared(await browser.get("about:blank"))


async def connect_extension(url_contains: str | None = None) -> Tab:
    """Attach to the user's REAL browser via the bridge extension.

    Ensures the local bridge daemon is running, then returns a single Tab bound
    to the browser's active tab (the extension attaches `chrome.debugger` to it).
    Unlike CDP mode this drives the user's live profile — no viewport override,
    no new tab.

    Raises:
        ConnectionError: the bridge won't start, or the extension isn't loaded /
            connected — the message carries the exact "Load unpacked" steps.
    """
    from ai_dev_browser.cdp import target as cdp_target

    from .ext_bridge import EXTENSION_BRIDGE_PORT, ensure_bridge_running
    from .extension import extension_load_instructions

    if not ensure_bridge_running():
        raise ConnectionError(
            f"Could not start the extension bridge on port {EXTENSION_BRIDGE_PORT}."
        )

    ws_url = f"ws://127.0.0.1:{EXTENSION_BRIDGE_PORT}"
    tinfo = cdp_target.TargetInfo(
        target_id=cdp_target.TargetID("ext-active"),
        type_="page",
        title="",
        url="",
        attached=True,
        can_access_opener=False,
    )
    # browser=None: single-tab, no multi-target discovery. Browser-level ops
    # (the cookie store, tab management) need extension-side shims — not yet.
    tab = Tab(ws_url, target=tinfo, browser=None)  # type: ignore[arg-type]
    try:
        await tab._ensure_connected()
        current = await tab.evaluate("location.href", timeout=5)
        tinfo.url = current or ""
    except Exception as e:
        raise ConnectionError(
            "Extension transport isn't ready (the bridge extension isn't "
            f"connected): {e}\n\n{extension_load_instructions()}"
        ) from e
    return tab


async def graceful_close_browser(
    host: str = DEFAULT_DEBUG_HOST,
    port: int = DEFAULT_DEBUG_PORT,
) -> bool:
    """Send CDP Browser.close() to gracefully shut down Chrome.

    This flushes cookies and other profile data to disk before exiting.
    Creates a temporary connection just for the close command.

    Args:
        host: Chrome debugging host
        port: Chrome debugging port

    Returns:
        True if close command was sent successfully, False on error.
    """
    try:
        # Get WebSocket URL
        url = f"http://{host}:{port}/json/version"
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(None, urllib.request.urlopen, url)
        info = json.loads(resp.read())
        ws_url = info["webSocketDebuggerUrl"]

        # Connect and send Browser.close
        conn = CDPConnection(ws_url)
        await conn.connect()
        try:
            await conn.send(cdp_browser.close(), _is_update=True)
        except Exception:
            # Connection may close before we get a response — that's expected
            pass
        finally:
            if not conn.closed:
                await conn.disconnect()

        # Remove cached BrowserClient for this port
        key = (host, port)
        existing = BrowserClient._instances.pop(key, None)
        if existing:
            existing.connection = None  # Already closed
            existing.targets.clear()

        return True
    except Exception as e:
        logger.debug("graceful_close_browser failed for %s:%d: %s", host, port, e)
        return False
