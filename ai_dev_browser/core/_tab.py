"""Tab class — wraps a CDP WebSocket connection to a browser tab."""

from __future__ import annotations

import asyncio
import base64
import logging
import pathlib
import typing
from typing import Any, Generator

from ai_dev_browser.cdp import (
    browser as cdp_browser,
    dom,
    dom_storage,
    emulation as cdp_emulation,
    input_ as cdp_input,
    page,
    runtime,
    target as cdp_target,
)

from ._element import Element, create, filter_recurse
from ._js import unwrap
from ._transport import (
    CDPConnection,
    CommandTimeout,
    MOUSE_EVENT_TIMEOUT,
    ProtocolException,
)
from .errors import js_snippet

if typing.TYPE_CHECKING:
    from .connection import BrowserClient

logger = logging.getLogger(__name__)

# CDP JSON-RPC error code for "method not found" — sent by the
# target when a domain method the client called isn't implemented
# there. Embedded CDP targets (Electron, CEF, packaged Chromium
# exposing --remote-debugging-port) commonly return this on
# Chrome-browser-specific methods like Browser.getWindowForTarget or
# Input.synthesizeScrollGesture. Anything else (protocol violation,
# malformed params, target crash) must not be silently downgraded.
_CDP_METHOD_NOT_FOUND = -32601


def _is_cdp_method_not_found(exc: ProtocolException) -> bool:
    """Robust match: prefer the numeric code from the CDP error dict;
    fall back to the human-readable variants for older transports
    that surface the error as a bare string."""
    err = exc.args[0] if exc.args else None
    if isinstance(err, dict) and err.get("code") == _CDP_METHOD_NOT_FOUND:
        return True
    text = str(exc)
    return str(_CDP_METHOD_NOT_FOUND) in text or "wasn't found" in text


class Tab:
    """CDP tab connection."""

    def __init__(
        self,
        websocket_url: str,
        target: cdp_target.TargetInfo,
        browser: BrowserClient,
    ):
        self._connection = CDPConnection(websocket_url)
        self._target = target
        self._browser = browser
        self._download_behavior: list | None = None
        self._initialized = False
        # Cache of {frame target id -> CDP flat-session id} for cross-origin
        # iframe routing; populated lazily by frame_session().
        self._frame_sessions: dict[str, str] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def target(self) -> cdp_target.TargetInfo:
        return self._target

    @property
    def browser(self) -> BrowserClient:
        return self._browser

    @property
    def closed(self) -> bool:
        return self._connection.closed

    def __getattr__(self, item):
        """Proxy attribute access to target (url, title, target_id, type_)."""
        try:
            return getattr(self._target, item)
        except AttributeError:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{item}'"
            ) from None

    # =========================================================================
    # Core CDP dispatch
    # =========================================================================

    async def _ensure_connected(self):
        """Ensure tab WebSocket is connected and essential domains are enabled.

        Detects both explicit disconnection (closed WebSocket) and implicit
        reconnection (_force_reconnect clears enabled_domains without resetting
        _initialized), and re-enables Page/DOM domains in both cases.
        """
        if self._connection.closed:
            logger.debug(
                "Tab WebSocket closed, reconnecting: %s",
                self._connection.websocket_url,
            )
            await self._connection.connect()
            self._initialized = False

        # Also check if domains were lost (e.g., _force_reconnect cleared them)
        if self._initialized and not self._connection.enabled_domains:
            self._initialized = False

        if not self._initialized:
            for domain_mod, enable_cmd in ((page, page.enable()), (dom, dom.enable())):
                try:
                    await self._connection.send(enable_cmd, _is_update=True)
                    # Track in enabled_domains so _register_handlers won't remove them
                    if domain_mod not in self._connection.enabled_domains:
                        self._connection.enabled_domains.append(domain_mod)
                except Exception:
                    pass
            self._initialized = True

    async def send(
        self,
        cdp_obj: Generator[dict[str, Any], dict[str, Any], Any],
        _is_update=False,
        *,
        timeout: float | None = None,
        retry_on_timeout: bool = False,
        session_id: str | None = None,
    ) -> Any:
        """Send CDP command and await response.

        Args:
            timeout: Per-call timeout in seconds. None = transport default
                (COMMAND_TIMEOUT, 30s). Pass a larger value for commands
                that legitimately take time (e.g. evaluate with
                await_promise on a long fetch) — that way the timeout
                doesn't fire and there's no ambiguity about whether the
                command executed.
            retry_on_timeout: If True, on timeout re-discover targets
                (Electron SPA may swap target IDs) and replay the command
                via send_raw(). Default False.

                Replay is unsafe for non-idempotent CDP commands —
                Runtime.evaluate of JS that issues a POST will execute
                the POST twice if retry fires. Only opt in when the
                command is provably idempotent or the timeout is known
                to be a target-loss artifact rather than a slow command.
        """
        await self._ensure_connected()
        try:
            return await self._connection.send(
                cdp_obj, _is_update=_is_update, timeout=timeout, session_id=session_id
            )
        except Exception as e:
            if not retry_on_timeout:
                raise
            method = getattr(e, "method", None)
            params = getattr(e, "params", None)
            if not method or not self._browser:
                raise

        # Opt-in retry path — caller asserted this command is safe to replay.
        logger.info("CDP timed out (%s), re-discovering targets and retrying", method)
        await self._rediscover_target()
        await self._ensure_connected()
        return await self._connection.send_raw(method, params)

    async def _rediscover_target(self):
        """Re-discover targets from browser and switch to new target if needed.

        Electron apps can change target IDs during SPA navigation, making
        the old WebSocket URL stale (connected but unresponsive). This method
        asks the browser for current targets and switches this Tab to a live
        page target if the old one is gone.
        """
        if not self._browser:
            return
        try:
            await self._browser.update_targets()
        except Exception:
            return

        old_url = self._connection.websocket_url

        # Check if our target still exists
        my_id = self._target.target_id
        still_exists = any(t._target.target_id == my_id for t in self._browser.targets)

        if still_exists:
            # Target exists but unresponsive — just force reconnect
            await self._connection.disconnect()
            self._initialized = False
            return

        # Target is gone — switch to the first available page target
        for tab in self._browser.tabs:
            if tab is not self:
                new_id = tab._target.target_id
                new_url = f"ws://{self._browser.host}:{self._browser.port}/devtools/page/{new_id}"
                logger.info("Target gone, switching: %s -> %s", old_url, new_url)
                await self._connection.disconnect()
                self._connection.websocket_url = new_url
                self._target = tab._target
                self._initialized = False
                return

        # No targets found — just force reconnect and hope for the best
        await self._connection.disconnect()
        self._initialized = False

    def add_handler(self, event_type, handler):
        """Register a CDP event handler."""
        self._connection.add_handler(event_type, handler)

    def remove_handler(self, event_type, handler) -> bool:
        """Unregister a CDP event handler (pair with add_handler)."""
        return self._connection.remove_handler(event_type, handler)

    # =========================================================================
    # JavaScript evaluation
    # =========================================================================

    async def evaluate(
        self,
        expression: str,
        await_promise=False,
        return_by_value=False,
        *,
        timeout: float | None = None,
        session_id: str | None = None,
    ):
        """Evaluate JS expression and return a plain Python value.

        Objects and arrays come back as dicts and lists — CDP's
        deep-serialization envelope is unwrapped here, so callers never see
        it and never need a `JSON.stringify` round trip.

        Args:
            timeout: Per-call CDP timeout (seconds). None = default 30s.
                Set higher for long-running awaited promises (long fetch,
                video generation, etc.) so the call doesn't time out.
                Note: timing out does NOT auto-retry — the JS may still
                be running server-side, and replay would double-execute
                any side effects.

        Raises:
            JsEvaluationError: the expression threw, or produced a value that
                cannot cross the CDP boundary (DOM node, function, pending
                promise). A page-side throw is an error, not a return value —
                returning it would make every caller's result silently
                type-shift, and the ones that read it as data would pass.
            CommandTimeout: no answer within `timeout`. The message names the
                expression, because "which eval hung?" is the whole question
                in a long test.
        """
        ser = runtime.SerializationOptions(
            serialization="deep",
            max_depth=10,
            additional_parameters={"maxNodeDepth": 10, "includeShadowTree": "all"},
        )
        try:
            remote_object, errors = await self.send(
                runtime.evaluate(
                    expression=expression,
                    user_gesture=True,
                    await_promise=await_promise,
                    return_by_value=return_by_value,
                    allow_unsafe_eval_blocked_by_csp=True,
                    serialization_options=ser,
                ),
                timeout=timeout,
                session_id=session_id,
            )
        except CommandTimeout as e:
            # The transport names the CDP method ("Runtime.evaluate") because
            # that is all it knows — correctly so. The expression is only in
            # scope here, so this is the one frame that can name it.
            # ASCII-only separator: an error message is the one string that
            # must never itself fail to print on a cp1252 console.
            raise CommandTimeout(
                f"{e.message} | expression: {js_snippet(expression)}",
                method=e.method,
                params=e.params,
            ) from None

        return unwrap(remote_object, errors, expression=expression)

    # =========================================================================
    # Cross-origin frame (OOPIF) routing
    # =========================================================================

    async def frame_session(self, frame: str) -> str:
        """Resolve a cross-origin child frame to a CDP flat-session id.

        Cross-origin iframes are separate CDP targets (OOPIFs) — the top page
        session can't see inside them (`DOM.getDocument(pierce)` stops at the
        boundary), so commands must carry the frame's `sessionId`. `frame`
        matches an iframe target by URL substring or by exact target id; the
        attach happens once and is cached.

        Raises ValueError if no cross-origin iframe matches (same-origin frames
        are reached without a session — they're not separate targets).
        """
        targets = await self.send(cdp_target.get_targets())
        iframes = [t for t in targets if getattr(t, "type_", None) == "iframe"]
        match = next(
            (t for t in iframes if t.target_id == frame or frame in (t.url or "")),
            None,
        )
        if match is None:
            available = [t.url for t in iframes if t.url] or ["(none)"]
            raise ValueError(
                f"no cross-origin iframe target matching {frame!r}. "
                f"cross-origin iframes on this page: {available} "
                "(pass any substring; same-origin iframes don't need --frame)"
            )
        cached = self._frame_sessions.get(match.target_id)
        if cached:
            return cached
        session_id = await self.send(
            cdp_target.attach_to_target(match.target_id, flatten=True)
        )
        self._frame_sessions[match.target_id] = session_id
        return session_id

    # =========================================================================
    # Element finding
    # =========================================================================

    async def find(self, text: str, best_match: bool = True, timeout: float = 10):
        """Find single element by text, with retry until timeout."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        text = text.strip()
        item = await self.find_element_by_text(text, best_match)
        while not item:
            await asyncio.sleep(0.5)
            item = await self.find_element_by_text(text, best_match)
            if loop.time() - start > timeout:
                return item
        return item

    async def find_all(self, text: str, timeout: float = 10):
        """Find all elements matching text, with retry until timeout."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        text = text.strip()
        items = await self.find_elements_by_text(text)
        while not items:
            await asyncio.sleep(0.5)
            items = await self.find_elements_by_text(text)
            if loop.time() - start > timeout:
                return items
        return items

    async def select(self, selector: str, timeout: float = 10):
        """Find single element by CSS selector, with retry until timeout."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        selector = selector.strip()
        item = await self.query_selector(selector)
        while not item:
            await asyncio.sleep(0.5)
            item = await self.query_selector(selector)
            if loop.time() - start > timeout:
                return item
        return item

    async def select_all(
        self, selector: str, timeout: float = 10, include_frames=False
    ):
        """Find all elements by CSS selector, with retry until timeout."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        selector = selector.strip()
        items = []
        if include_frames:
            # Search in iframes is handled at the Tab level, not Element level
            pass
        items.extend(await self.query_selector_all(selector))
        while not items:
            await asyncio.sleep(0.5)
            items = await self.query_selector_all(selector)
            if loop.time() - start > timeout:
                return items
        return items

    async def xpath(self, xpath: str, timeout: float = 2.5):
        """Find elements by XPath expression."""
        return await self.find_all(xpath, timeout=timeout)

    async def find_element_by_text(
        self, text: str, best_match: bool = False
    ) -> Element | None:
        """Find first element containing text."""
        doc = await self.send(dom.get_document(-1, True))
        text = text.strip()
        search_id, nresult = await self.send(dom.perform_search(text, True))
        node_ids = []
        if nresult:
            node_ids = await self.send(dom.get_search_results(search_id, 0, nresult))
        await self.send(dom.discard_search_results(search_id))

        items = []
        for nid in node_ids:
            node = filter_recurse(doc, lambda n: n.node_id == nid)
            if not node:
                continue
            try:
                elem = create(node, self, doc)
            except Exception:
                continue
            if elem.node_type == 3:
                # Text node — return parent element
                parent_node = filter_recurse(doc, lambda n: n.node_id == node.parent_id)
                if parent_node:
                    items.append(create(parent_node, self, doc))
                else:
                    items.append(elem)
            else:
                items.append(elem)

        try:
            if not items:
                return None
            if best_match:
                return min(items, key=lambda el: abs(len(text) - len(el.text_all)))
            return next((e for e in items if e), None)
        finally:
            await self.send(dom.disable())

    async def find_elements_by_text(self, text: str) -> list[Element]:
        """Find all elements containing text."""
        doc = await self.send(dom.get_document(-1, True))
        text = text.strip()
        search_id, nresult = await self.send(dom.perform_search(text, True))
        node_ids = []
        if nresult:
            node_ids = await self.send(dom.get_search_results(search_id, 0, nresult))
        await self.send(dom.discard_search_results(search_id))

        items = []
        for nid in node_ids:
            node = filter_recurse(doc, lambda n: n.node_id == nid)
            if not node:
                continue
            try:
                elem = create(node, self, doc)
            except Exception:
                continue
            if elem.node_type == 3:
                parent_node = filter_recurse(doc, lambda n: n.node_id == node.parent_id)
                if parent_node:
                    items.append(create(parent_node, self, doc))
                else:
                    items.append(elem)
            else:
                items.append(elem)

        await self.send(dom.disable())
        return items

    async def query_selector(self, selector: str) -> Element | None:
        """Find single element by CSS selector."""
        doc = await self.send(dom.get_document(-1, True))
        try:
            node_id = await self.send(dom.query_selector(doc.node_id, selector))
        except ProtocolException:
            await self.send(dom.disable())
            return None
        if not node_id:
            return None
        node = filter_recurse(doc, lambda n: n.node_id == node_id)
        if not node:
            return None
        return create(node, self, doc)

    async def query_selector_all(self, selector: str) -> list[Element]:
        """Find all elements by CSS selector."""
        doc = await self.send(dom.get_document(-1, True))
        try:
            node_ids = await self.send(dom.query_selector_all(doc.node_id, selector))
        except ProtocolException:
            await self.send(dom.disable())
            return []
        if not node_ids:
            return []
        items = []
        for nid in node_ids:
            node = filter_recurse(doc, lambda n: n.node_id == nid)
            if node:
                items.append(create(node, self, doc))
        return items

    # =========================================================================
    # Mouse / Input
    # =========================================================================

    async def mouse_move(self, x: float, y: float, steps: int = 10):
        """Move mouse to coordinates with intermediate steps."""
        if steps <= 1:
            await self.send(
                cdp_input.dispatch_mouse_event("mouseMoved", x=x, y=y),
                timeout=MOUSE_EVENT_TIMEOUT,
            )
            return
        # Get last known position (default 0,0)
        from_x, from_y = 0, 0
        for i in range(steps):
            t = (i + 1) / steps
            ix = from_x + (x - from_x) * t
            iy = from_y + (y - from_y) * t
            await self.send(
                cdp_input.dispatch_mouse_event("mouseMoved", x=ix, y=iy),
                timeout=MOUSE_EVENT_TIMEOUT,
            )

    async def mouse_click(
        self, x: float, y: float, button: str = "left", modifiers: int = 0
    ):
        """Click at coordinates."""
        btn = cdp_input.MouseButton(button)
        await self.send(
            cdp_input.dispatch_mouse_event(
                "mousePressed",
                x=x,
                y=y,
                button=btn,
                click_count=1,
                modifiers=modifiers,
            ),
            timeout=MOUSE_EVENT_TIMEOUT,
        )
        await self.send(
            cdp_input.dispatch_mouse_event(
                "mouseReleased",
                x=x,
                y=y,
                button=btn,
                click_count=1,
                modifiers=modifiers,
            ),
            timeout=MOUSE_EVENT_TIMEOUT,
        )

    async def mouse_drag(self, source, dest, steps: int = 10):
        """Drag from source to dest. Both are (x, y) tuples or have .x/.y attrs."""
        sx, sy = (
            (source[0], source[1])
            if isinstance(source, (tuple, list))
            else (source.x, source.y)
        )
        dx, dy = (
            (dest[0], dest[1]) if isinstance(dest, (tuple, list)) else (dest.x, dest.y)
        )

        btn = cdp_input.MouseButton("left")
        await self.send(
            cdp_input.dispatch_mouse_event(
                "mousePressed", x=sx, y=sy, button=btn, click_count=1
            ),
            timeout=MOUSE_EVENT_TIMEOUT,
        )
        for i in range(steps):
            t = (i + 1) / steps
            ix = sx + (dx - sx) * t
            iy = sy + (dy - sy) * t
            await self.send(
                cdp_input.dispatch_mouse_event("mouseMoved", x=ix, y=iy),
                timeout=MOUSE_EVENT_TIMEOUT,
            )
        await self.send(
            cdp_input.dispatch_mouse_event(
                "mouseReleased", x=dx, y=dy, button=btn, click_count=1
            ),
            timeout=MOUSE_EVENT_TIMEOUT,
        )

    # =========================================================================
    # Scroll
    # =========================================================================

    async def _scroll_by_viewport_percent(self, percent: float) -> None:
        """Scroll by `percent` of viewport height (positive = down,
        negative = up).

        Prefers Chrome's gesture-based path
        (`Browser.getWindowForTarget` for bounds +
        `Input.synthesizeScrollGesture` for a smooth swipe) so scroll
        looks human-like — the gesture-shape acceleration + easing
        matter for anti-bot heuristics that flag instant jumps.

        Falls back to `Runtime.evaluate` + `window.scrollBy` only
        when the gesture path returns CDP -32601 "method not found".
        That signals an embedded target (Electron, CEF, packaged
        Chromium exposing CDP via `--remote-debugging-port`) that
        doesn't implement Browser or synthesizeScrollGesture. On
        the fallback path, scroll events still fire so lazy-load /
        IntersectionObserver / scroll-listener triggers still work —
        we just lose the gesture-shape (which the embedded target
        can't observe anyway).
        """
        try:
            _window_id, bounds = await self.get_window()
            await self.send(
                cdp_input.synthesize_scroll_gesture(
                    x=0,
                    y=0,
                    y_distance=-(bounds.height * (percent / 100)),
                    y_overscroll=0,
                    x_overscroll=0,
                    prevent_fling=True,
                    repeat_delay_ms=0,
                    speed=7777,
                )
            )
        except ProtocolException as e:
            if not _is_cdp_method_not_found(e):
                raise
            await self.evaluate(
                f"window.scrollBy(0, window.innerHeight * {percent / 100})"
            )

    async def scroll_down(self, amount: int = 25):
        """Scroll down by percentage of viewport height."""
        await self._scroll_by_viewport_percent(amount)

    async def scroll_up(self, amount: int = 25):
        """Scroll up by percentage of viewport height."""
        await self._scroll_by_viewport_percent(-amount)

    # =========================================================================
    # Navigation
    # =========================================================================

    async def get(
        self, url: str = "about:blank", tab_new: bool = False, new_window: bool = False
    ):
        """Navigate to URL or open in new tab."""
        if tab_new or new_window:
            if self._browser:
                return await self._browser.get(url, tab_new, new_window)
        frame_id, loader_id, *_ = await self.send(page.navigate(url))
        await asyncio.sleep(0.5)
        return self

    async def back(self):
        """Go back in history."""
        await self.evaluate("window.history.back()")

    async def forward(self):
        """Go forward in history."""
        await self.evaluate("window.history.forward()")

    async def page_reload(
        self, ignore_cache: bool = True, script_to_evaluate_on_load: str = None
    ):
        """Reload page."""
        await self.send(
            page.reload(
                ignore_cache=ignore_cache,
                script_to_evaluate_on_load=script_to_evaluate_on_load,
            )
        )

    # =========================================================================
    # Page content
    # =========================================================================

    async def save_screenshot(
        self,
        filename: str = "auto",
        format: str = "jpeg",
        full_page: bool = False,
    ) -> str:
        """Take page_screenshot and save to file. Returns file path."""
        if format.lower() in ("jpg", "jpeg"):
            ext, format_ = ".jpg", "jpeg"
        else:
            ext, format_ = ".png", "png"

        if not filename or filename == "auto":
            import datetime

            dt_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"screenshot_{dt_str}{ext}"

        path = pathlib.Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = await self.send(
            page.capture_screenshot(format_=format_, capture_beyond_viewport=full_page)
        )
        if not data:
            raise ProtocolException("Could not take page_screenshot")

        path.write_bytes(base64.b64decode(data))
        return str(path)

    async def get_content(self) -> str:
        """Get page HTML content."""
        doc = await self.send(dom.get_document(-1, True))
        return await self.send(dom.get_outer_html(backend_node_id=doc.backend_node_id))

    # =========================================================================
    # Window management
    # =========================================================================

    async def get_window(self):
        """Get (window_id, bounds) for this tab."""
        return await self.send(
            cdp_browser.get_window_for_target(self._target.target_id)
        )

    async def set_viewport(self, width: int, height: int):
        """Set the render (layout) viewport via a device-metrics override.

        Overrides `window.innerWidth/innerHeight` AND `window.screen.width/height`
        (plus the CSS `device-width` media queries) so responsive layouts pick
        their desktop breakpoint. `deviceScaleFactor=1` keeps screenshots 1:1;
        `mobile=False` keeps desktop behaviour (no touch, no viewport-meta).
        Independent of the OS window and the underlying display size — this is
        the only viewport lever that works headless and on a small display.
        """
        await self.send(
            cdp_emulation.set_device_metrics_override(
                width=width,
                height=height,
                device_scale_factor=1,
                mobile=False,
                screen_width=width,
                screen_height=height,
            )
        )

    async def _set_window_state(self, state: str):
        window_id, _ = await self.get_window()
        bounds = cdp_browser.Bounds(window_state=cdp_browser.WindowState(state))
        await self.send(cdp_browser.set_window_bounds(window_id, bounds))

    async def maximize(self):
        await self._set_window_state("maximized")

    async def minimize(self):
        await self._set_window_state("minimized")

    async def fullscreen(self):
        await self._set_window_state("fullscreen")

    async def medimize(self):
        """Restore to normal window state."""
        await self._set_window_state("normal")

    async def activate(self):
        """Activate this tab (bring to front)."""
        await self.send(cdp_target.activate_target(self._target.target_id))

    async def bring_to_front(self):
        """Alias for activate()."""
        await self.activate()

    async def close(self):
        """Close this tab's WebSocket connection."""
        await self._connection.disconnect()

    # =========================================================================
    # Download
    # =========================================================================

    async def download_path(self, path):
        """Set download directory."""
        p = pathlib.Path(path)
        p.mkdir(parents=True, exist_ok=True)
        await self.send(
            cdp_browser.set_download_behavior(
                behavior="allow", download_path=str(p.resolve())
            )
        )
        self._download_behavior = ["allow", str(p.resolve())]

    async def download_file(self, url: str, filename=None):
        """Download file by injecting JS fetch + anchor click."""
        if not self._download_behavior:
            directory = pathlib.Path.cwd() / "downloads"
            directory.mkdir(exist_ok=True)
            await self.download_path(directory)
        if not filename:
            filename = url.rsplit("/", 1)[-1].split("?", 1)[0]

        code = """
        (elem) => {
            async function _dl(src, name) {
                const r = await fetch(src);
                const b = await r.blob();
                const href = URL.createObjectURL(b);
                const a = document.createElement('a');
                a.href = href; a.download = name;
                document.body.appendChild(a); a.click();
                setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(href); }, 500);
            }
            _dl('%s', '%s')
        }
        """ % (url, filename)

        body_elems = await self.query_selector_all("body")
        if body_elems:
            body = body_elems[0]
            await body.update()
            await self.send(
                runtime.call_function_on(
                    code,
                    object_id=body.object_id,
                    arguments=[runtime.CallArgument(object_id=body.object_id)],
                )
            )
        await asyncio.sleep(0.1)
        return filename

    # =========================================================================
    # Local storage
    # =========================================================================

    async def _get_origin(self) -> str:
        """Get current page origin via JS (more reliable than target.url)."""
        try:
            origin = await self.evaluate("window.location.origin")
            if origin and origin != "null":
                return origin
        except Exception:
            pass
        # Fallback to target URL
        url = self._target.url or ""
        return "/".join(url.split("/", 3)[:3])

    async def storage_get(self) -> dict:
        """Get localStorage items as dict."""
        origin = await self._get_origin()
        items = await self.send(
            dom_storage.get_dom_storage_items(
                dom_storage.StorageId(is_local_storage=True, security_origin=origin)
            )
        )
        return {item[0]: item[1] for item in items} if items else {}

    async def storage_set(self, items: dict):
        """Set localStorage items."""
        origin = await self._get_origin()
        await asyncio.gather(
            *(
                self.send(
                    dom_storage.set_dom_storage_item(
                        storage_id=dom_storage.StorageId(
                            is_local_storage=True, security_origin=origin
                        ),
                        key=str(k),
                        value=str(v),
                    )
                )
                for k, v in items.items()
            )
        )

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def sleep(self, t: float = 0.5):
        """Sleep for t seconds."""
        await asyncio.sleep(t)

    def __await__(self):
        return self.sleep(0.1).__await__()
