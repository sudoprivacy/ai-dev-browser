"""Shared viewers, target switching and handoff against an actual Chrome.

This is the reusable browser boundary. Application/LLM acceptance belongs in
the consuming host and must not be inferred from this test.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import aiohttp
import pytest
import websockets

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import (
    connect_browser,
    connect_extension,
    get_active_tab,
)
from ai_dev_browser.core.ext_bridge import bridge_status, run_bridge
from ai_dev_browser.core.navigation import page_goto
from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.provision import prepare_managed_extension_profile
from ai_dev_browser.remote.session import BrowserSession
from tests.integration.test_remote_view import navigate_owned_browser, wait_for

pytest_plugins = ["tests.integration.test_remote_view"]


@pytest.mark.parametrize(
    "transport",
    [
        "cdp",
        pytest.param(
            "extension",
            marks=pytest.mark.skipif(
                not os.environ.get("AI_DEV_BROWSER_MANAGED_EXTENSION_PROFILE"),
                reason="Managed Chrome policy fixture required",
            ),
        ),
    ],
)
async def test_two_viewers_share_human_input_then_ai_submits(
    remote_site, transport, tmp_path
):
    options = {"temp": True}
    if transport == "extension":
        profile = os.environ["AI_DEV_BROWSER_MANAGED_EXTENSION_PROFILE"]
        identity = json.loads(Path("/opt/browser/extension/identity.json").read_text())
        await prepare_managed_extension_profile(
            profile, extension_id=identity["id"], extra_args=["--no-sandbox"]
        )
        options = {"transport": "extension", "user_data_dir": profile}
    launched = await asyncio.to_thread(
        browser_start,
        headless=True,
        stealth=False,
        silent_stderr=True,
        extra_args=["--no-sandbox"] if sys.platform == "linux" else [],
        **options,
    )
    assert "error" not in launched, launched
    client = None
    try:
        if transport == "extension":
            client = await connect_extension(session_id=launched["session_id"])
            await page_goto(await get_active_tab(client), url=remote_site[0])
        else:
            await navigate_owned_browser(launched, remote_site[0])
            client = await connect_browser(session_id=launched["session_id"])
        async with aiohttp.ClientSession() as http:
            session = BrowserSession(client, http)
            try:
                state = await session.state()
                original = state["activeTargetId"]
                assert original == launched["automation_target_id"]
                with pytest.raises(ControlError, match="not_attached"):
                    await session.frame("panel", 0, 0)
                # A page cannot bypass the host lease through the raw local
                # extension bridge. Native SDK calls still reach the daemon.
                server, _ = await run_bridge(0)
                port = server.sockets[0].getsockname()[1]
                try:
                    assert await bridge_status(port) is not None
                    outcome = await session.agent_command(
                        0,
                        0,
                        "Runtime.evaluate",
                        {
                            "expression": f"new Promise(resolve=>{{const socket=new WebSocket('ws://127.0.0.1:{port}/devtools/browser');socket.onopen=()=>{{socket.close();resolve('connected')}};socket.onerror=()=>resolve('rejected')}})",
                            "awaitPromise": True,
                            "returnByValue": True,
                        },
                    )
                    assert outcome["result"]["value"] == "rejected", outcome
                    # Chrome extension origins remain usable, including on
                    # websockets 13's legacy server implementation.
                    async with websockets.connect(
                        f"ws://127.0.0.1:{port}",
                        origin="chrome-extension://" + "a" * 32,
                    ) as connection:
                        await connection.send(
                            json.dumps({"id": 1, "method": "_bridge.status"})
                        )
                        assert "result" in json.loads(await connection.recv())
                finally:
                    server.close()
                    await server.wait_closed()
                await session.attach("panel")
                await session.attach("tab-viewer")
                frame = await session.frame("panel", 0, 0)
                assert frame["data"] and frame["width"] > 100
                import base64

                (tmp_path / "shared-page.jpg").write_bytes(
                    base64.b64decode(frame["data"])
                )
                held = await session.take("user", 0, 0)
                epoch = held["controlEpoch"]
                await session.action(
                    "user",
                    epoch,
                    0,
                    {"kind": "input", "input": {"kind": "click", "x": 80, "y": 45}},
                )
                await session.action(
                    "user",
                    epoch,
                    0,
                    {
                        "kind": "input",
                        "input": {"kind": "text", "text": "Manual sign-in complete"},
                    },
                )
                # Every viewer observes the current lease; no stale cached frame.
                next_frame = await session.frame("tab-viewer", epoch, 0)
                assert next_frame["controlEpoch"] == epoch
                with pytest.raises(ControlError, match="held_by_user"):
                    await session.agent_command(
                        epoch,
                        0,
                        "Runtime.evaluate",
                        {
                            "expression": "document.querySelector('#name').value='bypass'"
                        },
                    )
                await session.detach("panel")
                assert (await session.frame("tab-viewer", epoch, 0))["data"]
                await session.detach("tab-viewer")
                assert session.control.state == "human"
                with pytest.raises(ControlError, match="not_attached"):
                    await session.frame("panel", epoch, 0)

                resumed, observed = await session.give_back("user", epoch, 0)
                assert observed["activeTargetId"] == original
                assert any(
                    node.get("value", {}).get("value") == "Manual sign-in complete"
                    for node in observed["accessibility"]
                )
                assert observed["frame"]["controlEpoch"] == resumed["controlEpoch"]
                await session.action(
                    "ai",
                    resumed["controlEpoch"],
                    0,
                    {"kind": "input", "input": {"kind": "click", "x": 80, "y": 110}},
                )
                await wait_for(lambda: asyncio.sleep(0, result=remote_site[1]), bool)
                assert len(remote_site[1]) == 1
                assert remote_site[1][0]["name"] == "Manual sign-in complete"
                assert remote_site[1][0]["trusted"] is True
                assert remote_site[1][0]["cookie"] == "isolated"

                # A new tab invalidates commands/frames prepared for the old one.
                epoch = resumed["controlEpoch"]
                await session.action("ai", epoch, 0, {"kind": "new-tab"})
                switched = await session.state()
                assert switched["activeTargetId"] != original
                with pytest.raises(ControlError, match="stale"):
                    await session.action("ai", epoch, 0, {"kind": "reload"})
                await session.action(
                    "ai",
                    epoch,
                    switched["targetEpoch"],
                    {"kind": "select-tab", "targetId": original},
                )
                assert (await session.state())["activeTargetId"] == original
                (tmp_path / "shared-session-evidence.json").write_text(
                    json.dumps(
                        {
                            "transport": transport,
                            "sameTargetAfterHandoff": observed["activeTargetId"]
                            == original,
                            "receipt": remote_site[1][0],
                            "browserPageCannotOpenRawBridge": True,
                            "staleTabActionRejected": True,
                            "disconnectRetainsHumanControl": True,
                        },
                        indent=2,
                    )
                )
            finally:
                await session.close()
    finally:
        if client:
            await client.close()
        stopped = await asyncio.to_thread(
            browser_stop, session_id=launched["session_id"]
        )
        assert stopped["stopped"], stopped
