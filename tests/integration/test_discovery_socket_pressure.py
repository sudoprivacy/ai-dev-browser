"""Discover a real owned Chrome without opening empty probe connections."""

import asyncio
import json
import os
from pathlib import Path
import socket
import sys

import pytest

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core import browser as browser_module
from ai_dev_browser.core.connection import connect_browser, get_active_tab
from ai_dev_browser.core.port import find_debug_chromes


async def test_real_discovery_uses_listener_inventory(tmp_path, monkeypatch):
    binary = os.environ.get("AI_DEV_BROWSER_CHROME")
    if not binary:
        pytest.skip("Requires an explicitly selected real Chrome binary")
    assert Path(binary).is_file()
    reserved = socket.socket()
    sentinel = None
    for _ in range(10):
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        candidate = socket.socket()
        try:
            candidate.bind(("127.0.0.1", port + 1))
        except OSError:
            candidate.close()
            reserved.close()
            reserved = socket.socket()
            continue
        sentinel = candidate
        break
    assert sentinel is not None, "Two consecutive owned fixture ports required"
    sentinel.listen()
    sentinel.setblocking(False)
    connections, requests = [], []

    async def http(reader, writer):
        connections.append(True)
        try:
            first = await reader.readline()
            if first:
                requests.append(first.decode("ascii").strip())
                body = b'{"Browser":"fixture HTTP service"}'
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                    + body
                )
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(http, sock=sentinel)
    browser = client = None
    startup_process = None
    is_starting = False
    startup_bind_attempts = []
    real_launch = browser_module.launch_chrome
    real_bind = socket.socket.bind

    def launch(**options):
        nonlocal startup_process, is_starting
        startup_process = real_launch(**options)
        is_starting = True
        return startup_process

    def bind(candidate, address):
        if is_starting and address == ("127.0.0.1", port):
            startup_bind_attempts.append(address)
        return real_bind(candidate, address)

    monkeypatch.setattr(browser_module, "launch_chrome", launch)
    monkeypatch.setattr(socket.socket, "bind", bind)
    try:
        reserved.close()
        browser = await asyncio.to_thread(
            browser_start,
            port=port,
            headless=True,
            temp=True,
            stealth=False,
            chrome_path=binary,
            silent_stderr=True,
            extra_args=(["--no-sandbox"] if sys.platform == "linux" else [])
            + ["--enable-logging", f"--log-file={tmp_path / 'chrome-startup.log'}"],
        )
        is_starting = False
        assert "error" not in browser, browser
        assert not startup_bind_attempts, startup_bind_attempts
        found = await asyncio.to_thread(find_debug_chromes, (port, port + 2))
        assert len(found) == 1 and found[0][0] == port, found
        client = await connect_browser(port=found[0][0])
        tab = await get_active_tab(client)
        assert await tab.evaluate("location.protocol") == "about:"
        assert requests == ["GET /json/version HTTP/1.1"], requests
        assert len(connections) == 1, (
            "Discovery must not open a separate empty TCP probe before HTTP",
            len(connections),
        )
        (tmp_path / "discovery-evidence.json").write_text(
            json.dumps(
                {
                    "ownedChromePort": port,
                    "discoveredPorts": [value[0] for value in found],
                    "nonChromeExcluded": True,
                    "fixtureConnections": len(connections),
                    "fixtureRequests": requests,
                    "actualChromeProtocol": "about:",
                },
                indent=2,
            ),
            encoding="utf8",
        )
    finally:
        is_starting = False
        (tmp_path / "startup-readiness-evidence.json").write_text(
            json.dumps(
                {
                    "startup": browser,
                    "startupBindAttempts": startup_bind_attempts,
                    "pid": startup_process.pid if startup_process else None,
                    "processExitCode": startup_process.poll()
                    if startup_process
                    else None,
                },
                indent=2,
            ),
            encoding="utf8",
        )
        reserved.close()
        try:
            if client is not None:
                await client.close()
            if browser and "error" not in browser:
                stopped = await asyncio.to_thread(
                    browser_stop, session_id=browser["session_id"]
                )
                assert stopped.get("stopped") and stopped.get("count") == 1, stopped
                assert startup_process.poll() is not None
        finally:
            try:
                if startup_process and startup_process.poll() is None:
                    await asyncio.to_thread(
                        browser_module._kill_process_tree, startup_process.pid
                    )
                    assert startup_process.poll() is not None
            finally:
                server.close()
                await server.wait_closed()
