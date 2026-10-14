"""The public host/AI worker uses one real browser in both native modes."""

import json
import secrets
import sys

import aiohttp
import pytest
from aiohttp import web

from ai_dev_browser.remote.worker import Worker, application

pytest_plugins = ["tests.integration.test_remote_view"]


@pytest.mark.parametrize("is_headless", [True, False])
async def test_native_worker_preserves_identity_handoff_and_cookie(
    remote_site, tmp_path, is_headless
):
    host_token, ai_token = secrets.token_hex(32), secrets.token_hex(32)
    worker = Worker(
        tmp_path,
        host_token,
        ai_token,
        display_mode="native",
        chrome_args=["--no-sandbox"] if sys.platform == "linux" else [],
    )
    runner = web.AppRunner(application(worker))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    origin = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    binding = {
        "orgId": "local",
        "userId": "fixture-user",
        "sessionId": "fixture-session",
    }
    controller = "user-fixture-controller"
    async with aiohttp.ClientSession() as http:

        async def host(action):
            async with http.post(
                origin + "/invoke",
                headers={"Authorization": "Bearer " + host_token},
                json={"binding": binding, "controller": controller, "action": action},
            ) as response:
                body = await response.json()
                assert response.status == 200, body
                return body

        async def agent(action, status=200):
            async with http.post(
                origin + "/agent",
                headers={"Authorization": "Bearer " + ai_token},
                json=action,
            ) as response:
                body = await response.json()
                assert response.status == status, body
                return body

        def epochs(state):
            return {key: state[key] for key in ("controlEpoch", "targetEpoch")}

        try:
            async with http.get(origin + "/binding") as response:
                assert response.status == 403
            await host({"kind": "state"})
            started = (
                await agent(
                    {"kind": "start", "isHeadless": is_headless, "transport": "cdp"}
                )
            )["session"]
            assert worker.display is None and not started["capabilities"]["windowView"]
            assert started["isHeadless"] is is_headless
            await agent({"kind": "navigate", "url": remote_site[0], **epochs(started)})
            observed = (await agent({"kind": "observe", **epochs(started)}))["session"]
            assert observed["browserSessionId"] == started["browserSessionId"]
            await host({"kind": "attach", "viewerId": "panel", "surface": "page"})
            await host({"kind": "attach", "viewerId": "tab", "surface": "page"})
            held = (await host({"kind": "take", **epochs(observed)}))["session"]
            assert held["isController"] and held["isHumanControlHeld"]
            blocked = await agent(
                {"kind": "navigate", "url": "about:blank", **epochs(held)}, status=409
            )
            assert blocked["error"] == "browser_control_held_by_user"
            await agent({"kind": "take", **epochs(held)}, status=409)
            frame = await host({"kind": "frame", "viewerId": "tab", **epochs(held)})
            assert frame["frame"]["data"]
            assert frame["session"]["activeTargetId"] == observed["activeTargetId"]
            await host(
                {
                    "kind": "input",
                    "input": {"kind": "click", "x": 80, "y": 40},
                    **epochs(held),
                }
            )
            await host(
                {
                    "kind": "input",
                    "input": {"kind": "text", "text": "Shared worker 中文"},
                    **epochs(held),
                }
            )
            returned = await host(
                {
                    "kind": "return",
                    "note": "Read the human's updated field",
                    **epochs(held),
                }
            )
            fresh = returned["session"]
            assert (
                fresh["browserSessionId"] == started["browserSessionId"]
                and fresh["profileId"] == started["profileId"]
            )
            await agent({"kind": "observe", **epochs(fresh)})
            result = await agent(
                {
                    "kind": "command",
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": "document.querySelector('#name').value",
                        "returnByValue": True,
                    },
                    **epochs(fresh),
                }
            )
            assert "Shared worker 中文" in json.dumps(result, ensure_ascii=False)
            result = await agent(
                {
                    "kind": "command",
                    "method": "Runtime.evaluate",
                    "params": {"expression": "document.cookie", "returnByValue": True},
                    **epochs(fresh),
                }
            )
            assert "profile=isolated" in json.dumps(result)
            await agent(
                {
                    "kind": "input",
                    "input": {
                        "kind": "click",
                        "x": 80,
                        "y": 105,
                    },
                    **epochs(fresh),
                }
            )
            await agent({"kind": "observe", **epochs(fresh)})
            assert len(remote_site[1]) == 1
            assert (
                remote_site[1][0]["trusted"]
                and remote_site[1][0]["name"] == "Shared worker 中文"
            )
            assert remote_site[1][0]["cookie"] == "isolated"
        finally:
            await runner.cleanup()
