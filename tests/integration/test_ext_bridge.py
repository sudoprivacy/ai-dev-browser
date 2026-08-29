"""The extension-transport bridge relays adb's CDP to the extension and back.

Hermetic: a fake "extension" (a WS client that mocks `chrome.debugger`
responses) stands in for the real Chrome extension, so this proves the relay —
and that adb's existing `CDPConnection` drives over the bridge *unchanged*, no
`--transport` code path needed on the CDP side — without a browser. Runs in CI.
"""

from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from ai_dev_browser.cdp import runtime
from ai_dev_browser.core._transport import CDPConnection, ProtocolException
from ai_dev_browser.core.ext_bridge import run_bridge


async def _fake_extension(port: int, ready: asyncio.Event):
    ws = await websockets.connect(f"ws://127.0.0.1:{port}")
    await ws.send(json.dumps({"_event": "attached", "tabId": 1, "url": "about:blank"}))
    ready.set()
    try:
        async for raw in ws:
            m = json.loads(raw)
            if "id" in m and "method" in m:
                result = (
                    {"result": {"type": "number", "value": 42}}
                    if m["method"] == "Runtime.evaluate"
                    else {}
                )
                await ws.send(json.dumps({"id": m["id"], "result": result}))
    except Exception:
        pass


@pytest.mark.asyncio
async def test_bridge_relays_cdp_between_driver_and_extension():
    port = 9539
    server, _ = await run_bridge(port)
    ready = asyncio.Event()
    ext = asyncio.create_task(_fake_extension(port, ready))
    try:
        await asyncio.wait_for(ready.wait(), 5)
        await asyncio.sleep(0.2)

        conn = CDPConnection(f"ws://127.0.0.1:{port}")
        await conn.connect()
        ro, _exc = await conn.send(
            runtime.evaluate("6*7", return_by_value=True), _is_update=True
        )
        assert ro.value == 42, "CDP result did not round-trip through the bridge"
        await conn.disconnect()
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
