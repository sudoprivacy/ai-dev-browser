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
from ai_dev_browser.core._transport import MAX_SIZE, CDPConnection, ProtocolException
from ai_dev_browser.core.connection import BrowserClient, get_active_tab
from ai_dev_browser.core.ext_bridge import run_bridge


async def test_bridge_preserves_large_replies_and_dom_events():
    """Real WS frames carry review metadata above the default server limit."""
    server, bridge = await run_bridge(0)
    port = server.sockets[0].getsockname()[1]
    payload = "x" * (5 * 1024 * 1024)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}") as extension:
            await extension.send(json.dumps({"_hello": True}))

            async def announced():
                while bridge.extension is None:
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(announced(), 3)
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/devtools/page/11", max_size=MAX_SIZE
            ) as driver:
                await driver.send(json.dumps({"id": 1, "method": "Runtime.evaluate"}))
                request = json.loads(await asyncio.wait_for(extension.recv(), 3))
                await extension.send(
                    json.dumps({"_gid": request["_gid"], "result": {"value": payload}})
                )
                reply = json.loads(await asyncio.wait_for(driver.recv(), 3))
                assert reply == {"id": 1, "result": {"value": payload}}
                await extension.send(
                    json.dumps(
                        {
                            "_event_tab": "11",
                            "method": "DOM.attributeModified",
                            "params": {"nodeId": 2, "name": "srcdoc", "value": payload},
                        }
                    )
                )
                event = json.loads(await asyncio.wait_for(driver.recv(), 3))
                assert event["method"] == "DOM.attributeModified"
                assert event["params"]["value"] == payload
                assert bridge.extension is not None
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_bridge_preserves_child_sessions_without_cross_tab_events():
    server, bridge = await run_bridge(0)
    port = server.sockets[0].getsockname()[1]
    seen = []

    async def extension():
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            await ws.send(json.dumps({"_hello": True, "session_id": "frame-fixture"}))
            pending = []
            async for raw in ws:
                command = json.loads(raw)
                seen.append(command)
                if command["params"].get("expression") == "disconnect":
                    await ws.close()
                    return
                if len(seen) <= 2:
                    pending.append(command)
                    if len(pending) < 2:
                        continue
                    for item in reversed(pending):
                        await ws.send(
                            json.dumps(
                                {
                                    "_gid": item["_gid"],
                                    "result": {"child": item["sessionId"]},
                                }
                            )
                        )
                    await ws.send(
                        json.dumps(
                            {
                                "_event_tab": "11",
                                "sessionId": "child-a",
                                "method": "Runtime.consoleAPICalled",
                                "params": {"marker": "only-first-tab"},
                            }
                        )
                    )
                else:
                    await ws.send(
                        json.dumps(
                            {"_gid": command["_gid"], "result": {"barrier": True}}
                        )
                    )

    task = asyncio.create_task(extension())
    try:
        async with asyncio.timeout(5):
            while bridge.extension is None:
                await asyncio.sleep(0.01)
        async with (
            websockets.connect(f"ws://127.0.0.1:{port}/devtools/page/11") as first,
            websockets.connect(f"ws://127.0.0.1:{port}/devtools/page/22") as second,
        ):
            for driver, session in ((first, "child-a"), (second, "child-b")):
                await driver.send(
                    json.dumps(
                        {
                            "id": 7,
                            "sessionId": session,
                            "method": "Runtime.evaluate",
                            "params": {"expression": "read"},
                        }
                    )
                )
            assert json.loads(await first.recv()) == {
                "id": 7,
                "sessionId": "child-a",
                "result": {"child": "child-a"},
            }
            assert json.loads(await second.recv()) == {
                "id": 7,
                "sessionId": "child-b",
                "result": {"child": "child-b"},
            }
            event = json.loads(await first.recv())
            assert event == {
                "method": "Runtime.consoleAPICalled",
                "params": {"marker": "only-first-tab"},
                "sessionId": "child-a",
            }
            # The ordered acknowledgement follows event dispatch. The other
            # tab must receive its response without an intervening child event.
            await second.send(
                json.dumps(
                    {
                        "id": 8,
                        "method": "Runtime.evaluate",
                        "params": {"expression": "barrier"},
                    }
                )
            )
            assert json.loads(await second.recv()) == {
                "id": 8,
                "result": {"barrier": True},
            }
            assert {(item["tab"], item["sessionId"]) for item in seen[:2]} == {
                ("11", "child-a"),
                ("22", "child-b"),
            }
            await first.send(
                json.dumps(
                    {
                        "id": 9,
                        "sessionId": "child-a",
                        "method": "Runtime.evaluate",
                        "params": {"expression": "disconnect"},
                    }
                )
            )
            failure = json.loads(await first.recv())
            assert failure == {
                "id": 9,
                "sessionId": "child-a",
                "error": {"message": "extension disconnected"},
            }
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.close()
        await server.wait_closed()


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
async def test_extension_transport_skips_render_viewport(monkeypatch):
    """get_active_tab must NOT push a render viewport in extension transport —
    that drives the user's real browser, where setDeviceMetricsOverride is
    unroutable ("no target" when no tab is attached) and one unwrapped step
    used to fail every tool. (The fake answers evaluate with 42, so innerWidth
    reads <1000 — without the skip the desktop viewport would be applied.)"""
    monkeypatch.delenv("AI_DEV_BROWSER_VIEWPORT", raising=False)
    port = 9541
    server, _ = await run_bridge(port)
    ready = asyncio.Event()
    seen: list = []
    ext = asyncio.create_task(_fake_extension(port, ready, seen))
    try:
        await asyncio.wait_for(ready.wait(), 5)
        await asyncio.sleep(0.2)
        browser = await BrowserClient.connect(
            host="127.0.0.1",
            port=port,
            ws_url=f"ws://127.0.0.1:{port}/devtools/browser",
        )
        browser.transport = "extension"  # what connect_extension marks
        tab = await get_active_tab(browser)
        assert tab is not None
        methods = [m for m, _ in seen]
        assert "Emulation.setDeviceMetricsOverride" not in methods, (
            f"extension transport must not push a render viewport: {methods}"
        )
        await browser.close()
    finally:
        ext.cancel()
        server.close()


async def _fake_extension_two_tabs(port, ready, seen):
    """Mock extension with TWO page targets that honors Target.closeTarget by
    dropping the target — so a subsequent getTargets reflects the removal, the
    way the real background.js does via chrome.tabs.remove."""
    ws = await websockets.connect(f"ws://127.0.0.1:{port}")
    await ws.send(json.dumps({"_hello": True, "account": "tester@example.com"}))
    ready.set()
    targets = {"1", "2"}
    try:
        async for raw in ws:
            m = json.loads(raw)
            gid = m.get("_gid")
            if gid is None:
                continue
            method = m.get("method")
            seen.append(
                (method, (m.get("params") or {}).get("targetId") or m.get("tab"))
            )
            if method == "Target.getTargets":
                result = {
                    "targetInfos": [
                        {
                            "targetId": t,
                            "type": "page",
                            "title": "",
                            "url": "about:blank",
                            "attached": True,
                            "canAccessOpener": False,
                        }
                        for t in sorted(targets)
                    ]
                }
            elif method == "Target.closeTarget":
                targets.discard((m.get("params") or {}).get("targetId"))
                result = {"success": True}
            else:
                result = {}
            await ws.send(json.dumps({"_gid": gid, "result": result}))
    except Exception:
        pass


@pytest.mark.asyncio
async def test_tab_close_routes_close_target_over_extension():
    """tab_close must actually close the tab in extension transport — send
    Target.closeTarget (the bridge maps it to chrome.tabs.remove), then re-fetch
    so `remaining` is honest. Before, it only dropped adb's WS and returned a
    stale count, so a no-op read as success."""
    from ai_dev_browser.core.tabs import tab_close

    port = 9543
    server, _ = await run_bridge(port)
    ready = asyncio.Event()
    seen: list = []
    ext = asyncio.create_task(_fake_extension_two_tabs(port, ready, seen))
    try:
        await asyncio.wait_for(ready.wait(), 5)
        await asyncio.sleep(0.2)
        browser = await BrowserClient.connect(
            host="127.0.0.1",
            port=port,
            ws_url=f"ws://127.0.0.1:{port}/devtools/browser",
        )
        browser.transport = "extension"
        assert len(browser.tabs) == 2, [t._target.target_id for t in browser.tabs]
        res = await tab_close(browser, tab_id=1)
        assert res["closed"] is True, res
        assert res["remaining"] == 1, res
        assert any(m == "Target.closeTarget" for m, _ in seen), seen
        await browser.close()
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
