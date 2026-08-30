"""Local bridge daemon for the extension transport.

Topology (why a daemon): the bridge extension is a WS *client* (extensions can't
listen), and adb tools are short-lived CLI processes. So a small persistent
daemon owns the middle: the extension dials it and stays connected; each adb call
connects as a "driver", speaks raw CDP, and the daemon relays that to the
extension's `chrome.debugger` and back. The extension connection survives across
adb calls — no 30s reconnect wait per command.

The daemon is a **CDP multiplexer**, so adb's ordinary CDP machinery
(`BrowserClient` + per-tab `Tab` connections, `tab_list`, `tab_switch`,
`get_active_tab`) drives over the extension *unchanged* — same code path as a
real `--remote-debugging-port` Chrome:

  - A driver opens a **browser-level** connection (path `/devtools/browser`) for
    `Target.*` / `Storage.*`, and one **per-tab** connection each
    (`/devtools/page/<targetId>`) for page/DOM/input/runtime commands.
  - All of them fan into the *single* extension socket. The daemon namespaces
    every driver command with a global id so responses route back to the right
    driver+id, and tags each per-tab connection with its targetId so the
    extension knows which `chrome.debugger` tab to hit and so CDP events route
    back to the connection that asked for them.

Role of the first frame: the extension leads with `{_hello: ...}`; a driver
leads with a CDP command `{id, method, ...}`.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging

import websockets

from .extension import EXTENSION_BRIDGE_PORT

logger = logging.getLogger(__name__)


def _conn_path(ws) -> str:
    """The HTTP path the driver connected on (routes browser-level vs per-tab).

    websockets>=11 exposes it at `ws.request.path`; fall back to `/` so a client
    that omits a path is treated as browser-level.
    """
    req = getattr(ws, "request", None)
    return getattr(req, "path", None) or "/"


def _target_id_from_path(path: str) -> str | None:
    """`/devtools/page/<targetId>` → `<targetId>`; anything else → None
    (browser-level: `/devtools/browser`, `/`, the status probe)."""
    marker = "/devtools/page/"
    if marker in path:
        return path.rsplit("/", 1)[-1] or None
    return None


class _Bridge:
    def __init__(self) -> None:
        self.extension: object | None = None  # single ws to the extension
        self.account: str | None = None  # profile email from the extension hello
        self._gid = itertools.count(1)  # global id namespace across all drivers
        # gid -> (driver_ws, original_id): where each in-flight command's
        # response must be delivered.
        self._pending: dict[int, tuple] = {}
        # targetId -> driver_ws: the per-tab connection to deliver that tab's
        # CDP events to.
        self._tab_conns: dict[str, object] = {}

    async def handler(self, ws):
        try:
            first = await ws.recv()
        except Exception:
            return
        try:
            m = json.loads(first)
        except Exception:
            return
        if "_hello" in m:
            await self._extension(ws, m)
        else:
            await self._driver(ws, _conn_path(ws), first)

    # ------------------------------------------------------------------ extension
    async def _extension(self, ws, hello):
        self.extension = ws
        self.account = hello.get("account")
        logger.info("extension connected (account=%s)", self.account)
        try:
            async for raw in ws:
                try:
                    m = json.loads(raw)
                except Exception:
                    continue
                if "_gid" in m:
                    # A command response — route back to the driver that sent it.
                    entry = self._pending.pop(m["_gid"], None)
                    if entry is None:
                        continue
                    driver_ws, orig_id = entry
                    out: dict = {"id": orig_id}
                    if "error" in m:
                        out["error"] = m["error"]
                    else:
                        out["result"] = m.get("result", {})
                    try:
                        await driver_ws.send(json.dumps(out))
                    except Exception:
                        pass
                elif "_event_tab" in m:
                    # A CDP event from a tab — deliver only to the driver holding
                    # that tab's connection (keeps each Tab's event stream clean).
                    conn = self._tab_conns.get(m["_event_tab"])
                    if conn is not None:
                        try:
                            await conn.send(
                                json.dumps(
                                    {
                                        "method": m.get("method"),
                                        "params": m.get("params", {}),
                                    }
                                )
                            )
                        except Exception:
                            pass
                elif "_hello" in m:
                    self.account = m.get("account")
        except websockets.exceptions.ConnectionClosed:
            pass  # extension disconnected — normal
        finally:
            if self.extension is ws:
                self.extension = None
                self.account = None
                # Fail every in-flight command so no driver hangs.
                for gid, (driver_ws, orig_id) in list(self._pending.items()):
                    try:
                        await driver_ws.send(
                            json.dumps(
                                {
                                    "id": orig_id,
                                    "error": {"message": "extension disconnected"},
                                }
                            )
                        )
                    except Exception:
                        pass
                self._pending.clear()

    # ------------------------------------------------------------------ drivers
    _LOGGED = (
        "Page.navigate",
        "Input.dispatch",
        "Runtime.evaluate",
        "Runtime.callFunctionOn",
    )

    def _log_action(self, method, params):
        # Surface security-meaningful actions (driving your REAL browser). Skip
        # low-level plumbing (Page.enable, DOM.getDocument, …) as noise.
        if not any(method.startswith(p) for p in self._LOGGED):
            return
        params = params or {}
        detail = ""
        if method == "Page.navigate":
            detail = " -> " + str(params.get("url", ""))[:120]
        elif method == "Runtime.evaluate":
            detail = " " + str(params.get("expression", ""))[:80].replace("\n", " ")
        logger.info("action: %s%s", method, detail)

    async def _driver(self, ws, path, first):
        target_id = _target_id_from_path(path)
        if target_id is not None:
            self._tab_conns[target_id] = ws
        try:
            await self._forward(ws, target_id, first)
            async for raw in ws:
                await self._forward(ws, target_id, raw)
        except websockets.exceptions.ConnectionClosed:
            pass  # the adb CLI process exited — normal per-call lifecycle
        finally:
            if target_id is not None and self._tab_conns.get(target_id) is ws:
                del self._tab_conns[target_id]

    async def _forward(self, ws, target_id, raw):
        try:
            msg = json.loads(raw)
        except Exception:
            return
        mid = msg.get("id")
        method = msg.get("method")

        # Daemon-local status query — answered from the daemon's own state, never
        # relayed. Lets browser_connect tell the failure states apart.
        if method == "_bridge.status":
            await ws.send(
                json.dumps(
                    {
                        "id": mid,
                        "result": {
                            "extension_connected": self.extension is not None,
                            "account": self.account,
                        },
                    }
                )
            )
            return

        if self.extension is None:
            # No extension: reply with a clean per-command error (echo the id so
            # the driver's CDPConnection resolves it) WITHOUT closing — closing
            # would cancel every pending transaction and spew warnings.
            await ws.send(
                json.dumps({"id": mid, "error": {"message": "extension not connected"}})
            )
            return

        self._log_action(method or "", msg.get("params"))
        gid = next(self._gid)
        self._pending[gid] = (ws, mid)
        try:
            await self.extension.send(
                json.dumps(
                    {
                        "_gid": gid,
                        "tab": target_id,
                        "method": method,
                        "params": msg.get("params") or {},
                    }
                )
            )
        except Exception:
            self._pending.pop(gid, None)
            await ws.send(
                json.dumps({"id": mid, "error": {"message": "extension send failed"}})
            )


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
    """Serve the bridge until cancelled. Returns (server, bridge) for tests."""
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
