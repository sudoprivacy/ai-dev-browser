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
        except websockets.exceptions.ConnectionClosed:
            pass  # extension disconnected — normal
        finally:
            if self.extension is ws:
                self.extension = None
                self.attached = None

    # Security-meaningful actions to surface in the action log (driving your
    # REAL browser). Low-level plumbing (Page.enable, DOM.getDocument, …) is
    # skipped as noise.
    _LOGGED = (
        "Page.navigate",
        "Input.dispatch",
        "Runtime.evaluate",
        "Runtime.callFunctionOn",
    )

    def _log_action(self, raw):
        try:
            m = json.loads(raw)
        except Exception:
            return
        method = m.get("method", "")
        if not any(method.startswith(p) for p in self._LOGGED):
            return
        params = m.get("params", {}) or {}
        detail = ""
        if method == "Page.navigate":
            detail = " -> " + str(params.get("url", ""))[:120]
        elif method == "Runtime.evaluate":
            detail = " " + str(params.get("expression", ""))[:80].replace("\n", " ")
        logger.info("action: %s%s", method, detail)

    async def _relay_from_driver(self, ws, raw):
        # Daemon-local status query — answered from the daemon's own state, NOT
        # relayed to the extension. Lets browser_connect tell the three failure
        # states apart (daemon down / no extension session / connected).
        try:
            probe = json.loads(raw)
        except Exception:
            probe = {}
        if probe.get("method") == "_bridge.status":
            await ws.send(
                json.dumps(
                    {
                        "id": probe.get("id"),
                        "result": {
                            "extension_connected": self.extension is not None,
                            "account": (self.attached or {}).get("account"),
                        },
                    }
                )
            )
            return

        if self.extension is not None:
            self._log_action(raw)
            await self.extension.send(raw)
            return
        # No extension: reply with a clean per-command error (echo the id so the
        # driver's CDPConnection resolves it, not hangs) WITHOUT closing the
        # connection — closing would cancel every pending transaction and spew
        # "listener stopped" warnings.
        try:
            fid = json.loads(raw).get("id")
        except Exception:
            fid = None
        await ws.send(
            json.dumps({"id": fid, "error": {"message": "extension not connected"}})
        )

    async def _driver(self, ws, first):
        self.driver = ws
        try:
            await self._relay_from_driver(ws, first)
            async for raw in ws:
                await self._relay_from_driver(ws, raw)
        except websockets.exceptions.ConnectionClosed:
            pass  # the adb CLI process exited — normal per-call lifecycle
        finally:
            if self.driver is ws:
                self.driver = None


def bridge_is_up(port: int = EXTENSION_BRIDGE_PORT) -> bool:
    """True if something is listening on the bridge port."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_bridge_running(
    port: int = EXTENSION_BRIDGE_PORT, timeout: float = 5.0
) -> bool:
    """Spawn the bridge daemon (detached, survives this CLI process) if it isn't
    already listening. Returns True once the port is up."""
    import platform
    import subprocess
    import sys
    import time

    if bridge_is_up(port):
        return True

    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if platform.system() == "Windows":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP — outlive the CLI call.
        kwargs["creationflags"] = 0x00000008 | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "ai_dev_browser.core.ext_bridge"], **kwargs)

    t0 = time.time()
    while time.time() - t0 < timeout:
        if bridge_is_up(port):
            return True
        time.sleep(0.1)
    return False


async def bridge_status(
    port: int = EXTENSION_BRIDGE_PORT, timeout: float = 3.0
) -> dict | None:
    """Query the daemon's own state (`{extension_connected, account}`) — a status
    frame it answers without relaying to the extension. None if unreachable."""
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            await ws.send(json.dumps({"id": 1, "method": "_bridge.status"}))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout))
            return resp.get("result")
    except Exception:
        return None


async def wait_for_extension(
    port: int = EXTENSION_BRIDGE_PORT, timeout: float = 5.0
) -> dict | None:
    """Poll until an extension has dialed into the daemon (returns its status),
    or timeout (None). A just-(re)loaded extension reconnects within ~a few
    seconds while its worker is alive; up to ~30s cold (alarm-driven)."""
    import time

    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        st = await bridge_status(port)
        if st and st.get("extension_connected"):
            return st
        await asyncio.sleep(0.3)
    return None


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
