"""Test fixture deadlines with real WebSocket peers, including a held handler."""

import asyncio
import inspect
import json

import pytest
import websockets

from tests.integration.live_cleanup import close_live_server


@pytest.mark.parametrize("backend", ["legacy", "asyncio"])
@pytest.mark.parametrize("held", [False, True])
async def test_live_server_cleanup_deadline_retains_failure(
    tmp_path, monkeypatch, backend, held
):
    if backend == "legacy":
        from websockets.legacy.server import serve
    else:
        from websockets.asyncio.server import serve

    connected = asyncio.Event()
    release = asyncio.Event()

    async def handler(socket):
        connected.set()
        if held:
            await release.wait()
        await socket.wait_closed()

    server = await serve(handler, "127.0.0.1", 0)
    # These fixture peers are local, even on a host with outbound proxies.
    for name in ("http_proxy", "https_proxy", "ws_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    monkeypatch.setenv("no_proxy", "")
    options = (
        {"proxy": None}
        if "proxy" in inspect.signature(websockets.connect).parameters
        else {}
    )
    peer = None
    try:
        peer = await websockets.connect(
            f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}", **options
        )
        await asyncio.wait_for(connected.wait(), 2)
        if held:
            with pytest.raises(AssertionError, match="Live bridge cleanup exceeded"):
                await asyncio.wait_for(
                    close_live_server(server, tmp_path, timeout=0.1), 2
                )
            assert (tmp_path / "extension-cleanup-stacks.txt").read_text()
            expected = "bridge-close-timeout"
        else:
            await asyncio.wait_for(close_live_server(server, tmp_path), 2)
            expected = "bridge-closed"
        history = json.loads((tmp_path / "extension-cleanup-evidence.json").read_text())
        assert history[-1]["phase"] == expected
    finally:
        release.set()
        if peer is not None:
            await peer.close()
        server.close()
        await asyncio.wait_for(server.wait_closed(), 2)
