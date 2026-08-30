"""The extension-transport bridge multiplexes adb's CDP onto one extension.

Hermetic: a fake "extension" (a WS client that mocks `chrome.debugger` /
`chrome.tabs`) stands in for the real Chrome extension, so this proves the
multiplexer — that adb's existing `CDPConnection` drives over the bridge
*unchanged* (browser-level Target.* on one connection, per-tab commands on
another, ids namespaced, per-tab routing) — without a browser. Runs in CI.
"""

from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from ai_dev_browser.cdp import runtime, target as cdp_target
from ai_dev_browser.core._transport import CDPConnection, ProtocolException
from ai_dev_browser.core.ext_bridge import run_bridge


async def _fake_extension(port: int, ready: asyncio.Event, seen: list):
    """Mock extension: hello first, then answer gid-wrapped commands, recording
    (method, tab) so tests can assert routing."""
    ws = await websockets.connect(f"ws://127.0.0.1:{port}")
    await ws.send(json.dumps({"_hello": True, "account": "tester@example.com"}))
    ready.set()
    try:
        async for raw in ws:
            m = json.loads(raw)
            gid = m.get("_gid")
            if gid is None:
                continue
            method = m.get("method")
            seen.append((method, m.get("tab")))
            if method == "Runtime.evaluate":
                result = {"result": {"type": "number", "value": 42}}
            elif method == "Target.getTargets":
                result = {
                    "targetInfos": [
                        {
                            "targetId": "1",
                            "type": "page",
                            "title": "",
                            "url": "about:blank",
                            "attached": True,
                            "canAccessOpener": False,
                        }
                    ]
                }
            else:
                result = {}
            await ws.send(json.dumps({"_gid": gid, "result": result}))
    except Exception:
        pass


@pytest.mark.asyncio
async def test_bridge_multiplexes_browser_and_per_tab_connections():
    port = 9539
    server, _ = await run_bridge(port)
    ready = asyncio.Event()
    seen: list = []
    ext = asyncio.create_task(_fake_extension(port, ready, seen))
    try:
        await asyncio.wait_for(ready.wait(), 5)
        await asyncio.sleep(0.2)

        # Browser-level connection → Target.getTargets, tab=None.
        bconn = CDPConnection(f"ws://127.0.0.1:{port}/devtools/browser")
        await bconn.connect()
        infos = await bconn.send(cdp_target.get_targets(), _is_update=True)
        assert any(t.target_id == "1" for t in infos), "getTargets did not round-trip"
        assert ("Target.getTargets", None) in seen, (
            "browser-level cmd must carry tab=None"
        )

        # Per-tab connection → Runtime.evaluate is tagged with the path's tabId.
        tconn = CDPConnection(f"ws://127.0.0.1:{port}/devtools/page/1")
        await tconn.connect()
        ro, _exc = await tconn.send(
            runtime.evaluate("6*7", return_by_value=True), _is_update=True
        )
        assert ro.value == 42, "CDP result did not round-trip through the bridge"
        assert ("Runtime.evaluate", "1") in seen, "per-tab cmd must carry its targetId"

        await tconn.disconnect()
        await bconn.disconnect()
    finally:
        ext.cancel()
        server.close()


@pytest.mark.asyncio
async def test_driver_without_extension_gets_clean_error_not_hang():
    port = 9540
    server, _ = await run_bridge(port)
    try:
        conn = CDPConnection(f"ws://127.0.0.1:{port}")
        await conn.connect()
        with pytest.raises(ProtocolException):
            await conn.send(
                runtime.evaluate("1", return_by_value=True), _is_update=True, timeout=3
            )
        await conn.disconnect()
    finally:
        server.close()
