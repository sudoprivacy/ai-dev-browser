"""Local bridge daemon for the extension transport.

Topology (why a daemon): the bridge extension is a WS *client* (extensions can't
listen), and adb tools are short-lived CLI processes. So a small persistent
daemon owns the middle: the extension dials it and stays connected; each adb call
connects as a "driver", speaks raw CDP, and the daemon relays that to the
extension's `chrome.debugger` and back. The extension connection survives across
adb calls — no 30s reconnect wait per command.

Both sides connect to the same port and are told apart by their first frame:
  - driver    → a CDP command `{id, method, params}`
  - extension → an `{_event: ...}` handshake (e.g. `attached`)

MVP: one extension, one active driver at a time, single active tab (the
extension attaches `chrome.debugger` to the active tab). Multi-target / browser-
level shims come later.
"""

from __future__ import annotations

import asyncio
import json
import logging

import websockets

from .extension import EXTENSION_BRIDGE_PORT

logger = logging.getLogger(__name__)


class _Bridge:
    def __init__(self) -> None:
        self.extension: object | None = None  # ws to the extension
        self.driver: object | None = None  # ws to the current adb driver
        self.attached: dict | None = None  # last {_event: attached} payload

    async def handler(self, ws, *_):
        try:
            first = await ws.recv()
        except Exception:
            return
        try:
            m = json.loads(first)
        except Exception:
            return
        # Role by first frame: a driver leads with a CDP command; the extension
        # leads with an `_event` handshake.
        if "id" in m and "method" in m:
            await self._driver(ws, first)
        else:
            await self._extension(ws, m)

    async def _extension(self, ws, first_msg):
        self.extension = ws
        if first_msg.get("_event") == "attached":
            self.attached = first_msg
        logger.info("extension connected (%s)", first_msg.get("_event"))
        try:
            async for raw in ws:
                try:
                    m = json.loads(raw)
                except Exception:
                    continue
                if "_event" in m:
                    if m.get("_event") == "attached":
                        self.attached = m
                    continue  # handshake frames are internal, never relayed
                # responses ({id,result}) and CDP events ({method,params}) →
                # forward to the driver verbatim
                if self.driver is not None:
                    try:
                        await self.driver.send(raw)
                    except Exception:
                        pass
        finally:
            if self.extension is ws:
                self.extension = None
                self.attached = None

    async def _driver(self, ws, first):
        if self.extension is None:
            # Echo the command id so the driver's CDPConnection resolves it as a
            # clean protocol error instead of hanging to timeout.
            try:
                fid = json.loads(first).get("id")
            except Exception:
                fid = None
            await ws.send(
                json.dumps({"id": fid, "error": {"message": "extension not connected"}})
            )
            return
        self.driver = ws
        try:
            await self.extension.send(first)  # relay the first command
            async for raw in ws:
                if self.extension is not None:
                    await self.extension.send(raw)
        finally:
            if self.driver is ws:
                self.driver = None


async def run_bridge(port: int = EXTENSION_BRIDGE_PORT):
    """Serve the bridge until cancelled. Returns the server (for tests)."""
    bridge = _Bridge()
    server = await websockets.serve(bridge.handler, "127.0.0.1", port)
    logger.info("extension bridge listening on 127.0.0.1:%d", port)
    return server, bridge


def _main():  # pragma: no cover - daemon entrypoint
    logging.basicConfig(level=logging.INFO)

    async def _serve():
        server, _ = await run_bridge()
        await server.wait_closed()

    asyncio.run(_serve())


if __name__ == "__main__":  # pragma: no cover
    _main()
