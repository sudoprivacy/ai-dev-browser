"""The handshake snapshot and actual driver lifetime must describe one identity."""

from types import SimpleNamespace

import pytest

from ai_dev_browser.core import _session, browser, connection, ext_bridge


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
