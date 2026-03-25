"""Async WebSocket transport for Chrome DevTools Protocol.

Replaces nodriver's Connection/Transaction classes with a simplified
implementation that uses the same CDP generator protocol.
"""

from __future__ import annotations

import asyncio
import collections
import importlib
import itertools
import json
import logging
import types
from asyncio import iscoroutinefunction
from typing import Any, Callable, Generator

import websockets
import websockets.asyncio.client
import websockets.exceptions

from ai_dev_browser import cdp

logger = logging.getLogger(__name__)

MAX_SIZE: int = 2**28
PING_TIMEOUT: int = 900  # 15 minutes
COMMAND_TIMEOUT: int = 30  # seconds per CDP command


class ProtocolException(Exception):
    """CDP protocol error."""

    def __init__(self, *args):
        self.message = None
        self.code = None
        self.args = args
        if isinstance(args[0], dict):
            self.message = args[0].get("message")
            self.code = args[0].get("code")
        else:
            self.message = "| ".join(str(x) for x in args)

    def __str__(self):
        return f"{self.message} [code: {self.code}]" if self.code else f"{self.message}"


class Transaction(asyncio.Future):
    """Wraps a CDP generator into a Future that resolves when response arrives.

    CDP methods return generators that:
    1. yield {"method": ..., "params": ...}  (the request)
    2. receive the response dict via .send()
    3. raise StopIteration with parsed result as .value
    """

    def __init__(self, cdp_obj: Generator):
        super().__init__()
        self.__cdp_obj__ = cdp_obj
        self.id: int | None = None
        self.method, *params = next(self.__cdp_obj__).values()
        self.params = params.pop() if params else {}

    @property
    def message(self) -> str:
        return json.dumps({"method": self.method, "params": self.params, "id": self.id})

    def __call__(self, **response):  # type: ignore[override]
        """Process CDP response: feed to generator or set exception."""
        if "error" in response:
            return self.set_exception(ProtocolException(response["error"]))
        try:
            self.__cdp_obj__.send(response.get("result", {}))  # type: ignore[arg-type]
        except StopIteration as e:
            self.set_result(e.value)
        except KeyError as e:
            raise KeyError(f"key '{e.args}' not found in response: {response}") from e


def _cdp_get_module(domain: str | types.ModuleType):
    """Get CDP domain module by name or module reference."""
    if isinstance(domain, types.ModuleType):
        return domain
    if domain == "input":
        domain = "input_"
    mod = getattr(cdp, domain, None)
    if mod:
        return mod
    return importlib.import_module(domain)


class CDPConnection:
    """Async WebSocket connection to a CDP endpoint.

    Handles sending CDP commands (generator protocol), receiving responses,
    and dispatching CDP events to registered handlers.
    """

    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self._websocket: websockets.asyncio.client.ClientConnection | None = None
        self._listener_task: asyncio.Task | None = None
        self._counter = itertools.count(0)
        self._pending: dict[int, Transaction] = {}
        self.handlers: dict[type, list[Callable]] = collections.defaultdict(list)
        self.enabled_domains: list = []

    @property
    def closed(self) -> bool:
        if not self._websocket:
            return True
        return bool(self._websocket.close_code)

    async def connect(self):
        """Open WebSocket and start listener."""
        if self._websocket and not self._websocket.close_code:
            return  # already connected
        self._websocket = await websockets.connect(
            self.websocket_url,
            ping_timeout=PING_TIMEOUT,
            max_size=MAX_SIZE,
        )
        self._listener_task = asyncio.ensure_future(self._listener())
        await self._register_handlers()

    async def disconnect(self):
        """Close WebSocket and stop listener."""
        if self._listener_task:
            self._listener_task.cancel()
            self._listener_task = None
        if self._websocket:
            self.enabled_domains.clear()
            await self._websocket.close()

    async def send(
        self,
        cdp_obj: Generator[dict[str, Any], dict[str, Any], Any],
        _is_update: bool = False,
    ) -> Any:
        """Send a CDP command and await the response.

        Auto-reconnects if WebSocket is dead. On send failure, reconnects
        and raises (caller can retry with a fresh generator).
        """
        if self.closed:
            await self.connect()
        if not _is_update:
            await self._register_handlers()
        tx = Transaction(cdp_obj)
        tx.id = next(self._counter)
        self._pending[tx.id] = tx
        try:
            await self._websocket.send(tx.message)
        except Exception as e:
            self._pending.pop(tx.id, None)
            # Connection is broken — force reconnect so next call works
            logger.debug("WebSocket send failed, forcing reconnect: %s", e)
            await self._force_reconnect()
            raise ProtocolException(f"WebSocket send failed: {e}")
        try:
            return await asyncio.wait_for(tx, timeout=COMMAND_TIMEOUT)
        except asyncio.TimeoutError:
            self._pending.pop(tx.id, None)
            # Timeout likely means connection is dead — force reconnect
            logger.debug("CDP command timed out (%s), forcing reconnect", tx.method)
            await self._force_reconnect()
            raise ProtocolException(
                f"CDP command timed out after {COMMAND_TIMEOUT}s: {tx.method}"
            )

    async def _force_reconnect(self):
        """Disconnect and reconnect the WebSocket."""
        try:
            await self.disconnect()
        except Exception:
            pass
        await self.connect()

    def add_handler(
        self,
        event_type: type | types.ModuleType | list[type],
        handler: Callable,
    ):
        """Register an event handler.

        Args:
            event_type: CDP event class, module (registers all events in module),
                        or list of event classes.
            handler: Sync or async callback. Called with (event) or (event, connection).
        """
        if not isinstance(event_type, list):
            event_type = [event_type]  # type: ignore[assignment,list-item]
        for evt in event_type:
            if isinstance(evt, types.ModuleType):
                import inspect

                for name, obj in inspect.getmembers_static(evt):
                    if name.isupper() or not name[0].isupper():
                        continue
                    if type(obj) is type:
                        self.handlers[obj].append(handler)
            else:
                self.handlers[evt].append(handler)

    # Domains that should never be removed by _register_handlers cleanup.
    # These are either always-on (target, storage, input_) or essential
    # for core operations (page, dom) — enabled by Tab._ensure_connected().
    _PROTECTED_DOMAINS = None  # Populated lazily to avoid import-time issues

    @classmethod
    def _get_protected_domains(cls):
        if cls._PROTECTED_DOMAINS is None:
            cls._PROTECTED_DOMAINS = {
                cdp.target,
                cdp.storage,
                cdp.input_,
                cdp.page,
                cdp.dom,
            }
        return cls._PROTECTED_DOMAINS

    async def _register_handlers(self):
        """Auto-enable CDP domains for registered event handlers.

        Does NOT remove domains that were explicitly enabled (page, dom, etc.)
        even if they have no event handlers — those are needed for commands.
        """
        protected = self._get_protected_domains()
        enabled_copy = self.enabled_domains.copy()
        for event_type in list(self.handlers):
            if not self.handlers[event_type]:
                self.handlers.pop(event_type, None)
                continue
            if not isinstance(event_type, type):
                continue
            domain_mod = _cdp_get_module(event_type.__module__.rsplit(".", 1)[-1])
            if domain_mod in self.enabled_domains:
                if domain_mod in enabled_copy:
                    enabled_copy.remove(domain_mod)
                continue
            if domain_mod in protected:
                continue
            try:
                self.enabled_domains.append(domain_mod)
                await self.send(domain_mod.enable(), _is_update=True)
            except Exception:
                logger.debug("Failed to enable domain %s", domain_mod, exc_info=True)
                try:
                    self.enabled_domains.remove(domain_mod)
                except ValueError:
                    pass
        # Remove domains that no longer have handlers, EXCEPT protected ones
        for ed in enabled_copy:
            if ed in protected:
                continue
            try:
                self.enabled_domains.remove(ed)
            except ValueError:
                pass

    def _cancel_pending(self, reason: str = "connection closed"):
        """Cancel all pending transactions (e.g., when WebSocket closes)."""
        for tx_id, tx in list(self._pending.items()):
            if not tx.done():
                tx.set_exception(ProtocolException(reason))
        self._pending.clear()

    async def _listener(self):
        """Background task: receive messages, dispatch responses and events."""
        try:
            await self._listener_loop()
        finally:
            self._cancel_pending("WebSocket listener stopped")

    async def _listener_loop(self):
        while True:
            try:
                raw = await asyncio.wait_for(self._websocket.recv(), 0.05)
            except asyncio.TimeoutError:
                await asyncio.sleep(0.05)
                continue
            except websockets.exceptions.ConnectionClosedOK:
                break
            except websockets.exceptions.ConnectionClosed:
                break
            except Exception:
                logger.info("WebSocket recv error", exc_info=True)
                break

            message = json.loads(raw)
            if "id" in message:
                # Response to a command
                tx = self._pending.pop(message["id"], None)
                if tx:
                    tx(**message)
            else:
                # CDP event
                try:
                    event = cdp.util.parse_json_event(message)
                except Exception:
                    continue
                callbacks = self.handlers.get(type(event))
                if not callbacks:
                    continue
                for callback in callbacks:
                    try:
                        if iscoroutinefunction(callback):
                            try:
                                asyncio.create_task(callback(event, self))
                            except TypeError:
                                asyncio.create_task(callback(event))
                        else:
                            try:
                                callback(event, self)
                            except TypeError:
                                callback(event)
                    except Exception:
                        logger.warning(
                            "Exception in handler for %s",
                            type(event).__name__,
                            exc_info=True,
                        )
