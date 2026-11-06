"""Read native listener state while the service retains its socket ownership."""

import socket

import pytest

from ai_dev_browser.core import port as ports


@pytest.mark.parametrize("probe", ["is_port_in_use", "_fast_listening_check"])
@pytest.mark.parametrize("is_listening", [False, True])
def test_liveness_observes_native_listener_without_claiming_port(
    monkeypatch, probe, is_listening
):
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        if is_listening:
            server.listen()
        real_bind = socket.socket.bind

        def bind(client, address):
            assert address != ("127.0.0.1", port), (
                "A liveness observer claimed the service port"
            )
            return real_bind(client, address)

        monkeypatch.setattr(socket.socket, "bind", bind)
        assert getattr(ports, probe)(port=port) is is_listening
