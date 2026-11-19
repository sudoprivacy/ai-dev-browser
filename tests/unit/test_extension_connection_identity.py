"""The handshake snapshot and actual driver lifetime must describe one identity."""

import asyncio
from types import SimpleNamespace

import pytest

from ai_dev_browser.core import _session, browser, connection, ext_bridge


async def test_browser_connection_cache_keeps_event_loops_separate(monkeypatch):
    class LoopBoundSocket:
        def __init__(self, url):
            self.owner = asyncio.get_running_loop()
            self.closed = False

        async def connect(self):
            assert asyncio.get_running_loop() is self.owner

        async def send(self, *args, **kwargs):
            assert asyncio.get_running_loop() is self.owner

        async def disconnect(self):
            assert asyncio.get_running_loop() is self.owner
            self.closed = True

    async def refresh(client):
        assert asyncio.get_running_loop() is client.connection.owner

    monkeypatch.setattr(connection, "CDPConnection", LoopBoundSocket)
    monkeypatch.setattr(connection.BrowserClient, "update_targets", refresh)
    address = ("127.0.0.1", 9522, "ws://127.0.0.1:9522/devtools/browser?session=one")

    async with await connection.BrowserClient.connect(*address) as viewer:
        assert await connection.BrowserClient.connect(*address) is viewer

        async def run_worker():
            async with await connection.BrowserClient.connect(*address) as worker:
                assert worker is not viewer
                assert await connection.BrowserClient.connect(*address) is worker

        await asyncio.to_thread(lambda: asyncio.run(run_worker()))
        assert not viewer.connection.closed
        assert await connection.BrowserClient.connect(*address) is viewer


@pytest.mark.parametrize("bound", [False, True])
async def test_connect_refuses_session_change_even_when_target_ids_collide(
    monkeypatch, bound
):
    status = {
        "session_id": "original",
        "profile_id": "profile",
        "automation_target_id": "42",
        "extension_version": "0.4.7",
    }
    record = {
        "session_id": "extension-original",
        "transport": "extension",
        "profile_id": "profile",
        "automation_target_id": "42",
        "owner": "external",
        "profile_owner": "user",
    }
    saved = []
    monkeypatch.setattr(_session, "read", lambda identity: record.copy())
    monkeypatch.setattr(_session, "write", lambda value: saved.append(value.copy()))
    monkeypatch.setattr(_session, "pending_launch", lambda port: None)
    monkeypatch.setattr(ext_bridge, "ensure_bridge_running", lambda **kw: True)

    async def handshake(**kw):
        return status

    monkeypatch.setattr(ext_bridge, "wait_for_extension", handshake)
    closed = []

    async def close():
        closed.append(True)

    # Model a profile/authorization switch between the snapshot and connect.
    # Both browsers may use the same numeric chrome.tabs ID. No Chrome input
    # or ownership RPC may be sent through the replacement connection.
    async def forbidden_send(*args, **kw):
        pytest.fail("A replacement connection must be refused before further RPCs")

    client = SimpleNamespace(
        tabs=[
            SimpleNamespace(
                _target=SimpleNamespace(
                    target_id="42", url="https://replacement.invalid/private"
                )
            )
        ],
        connection=SimpleNamespace(
            websocket_url="ws://127.0.0.1:9522/devtools/browser?session=replacement",
            send=forbidden_send,
        ),
        close=close,
    )

    async def connect():
        return client

    monkeypatch.setattr(connection, "connect_extension", connect)
    result = await browser.browser_connect(
        transport="extension", session_id=record["session_id"] if bound else None
    )
    assert result["connected"] is False and result["page_available"] is False
    assert result["error_code"] == "session_changed" and result["retryable"] is False
    assert result["session_id"] == record["session_id"]
    assert result["tabs"] == result["targets"] == [] and result["tab_count"] == 0
    assert closed == [True]
    assert all(item["session_id"] == record["session_id"] for item in saved)
