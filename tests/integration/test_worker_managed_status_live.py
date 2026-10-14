"""Concurrent status reads during an actual signed-extension browser stop."""

import asyncio
import json
import os
import secrets
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web

from ai_dev_browser.remote.worker import Worker, application

pytestmark = pytest.mark.skipif(
    not os.environ.get("AI_DEV_BROWSER_MANAGED_EXTENSION_PROFILE"),
    reason="Requires the isolated signed managed Chrome image",
)


@pytest.mark.parametrize("is_headless", [True, False])
async def test_managed_stop_keeps_status_and_the_human_lease(tmp_path, is_headless):
    host_token, ai_token = secrets.token_hex(32), secrets.token_hex(32)
    worker = Worker(
        tmp_path,
        host_token,
        ai_token,
        display_mode="x11",
        extension_directory=Path("/opt/browser/extension"),
        chrome_args=["--no-sandbox"],
    )
    runner = web.AppRunner(application(worker))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    origin = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    binding = {"orgId": "fixture", "userId": "owner", "sessionId": "owned-stop"}
    controller = "user-atomic-stop"
    try:
        async with aiohttp.ClientSession() as http:

            async def host(action):
                async with http.post(
                    origin + "/invoke",
                    headers={"Authorization": "Bearer " + host_token},
                    json={
                        "binding": binding,
                        "controller": controller,
                        "action": action,
                    },
                ) as response:
                    assert response.status == 200, await response.text()
                    return (await response.json())["session"]

            def epochs(value):
                return {key: value[key] for key in ("controlEpoch", "targetEpoch")}

            await host({"kind": "state"})
            async with http.post(
                origin + "/agent",
                headers={"Authorization": "Bearer " + ai_token},
                json={
                    "kind": "start",
                    "transport": "extension",
                    "isHeadless": is_headless,
                },
            ) as response:
                assert response.status == 200, await response.text()
                started = (await response.json())["session"]
            assert started["transport"] == "extension"
            assert started["isHeadless"] is is_headless
            assert bool(worker.display) is not is_headless
            held = await host({"kind": "take", **epochs(started)})
            stopping = asyncio.create_task(host({"kind": "stop", **epochs(held)}))
            snapshots = await asyncio.gather(
                *(host({"kind": "state"}) for _ in range(8))
            )
            stopped = await stopping
            assert all(
                value["state"] in ("human", "pausing", "stopped") for value in snapshots
            )
            assert all(value["isHumanControlHeld"] for value in snapshots)
            for value in snapshots:
                if value["state"] == "pausing":
                    assert value["tabs"] == [] and value["activeTargetId"] is None
                    assert not value["capabilities"]["pageView"]
                    assert not value["capabilities"]["windowView"]
            assert stopped["state"] == "stopped" and stopped["isController"]
            assert stopped["profileId"] == started["profileId"]
            assert (
                worker.session is None
                and worker.display is None
                and worker.browser is None
            )
            (tmp_path / "atomic-stop-evidence.json").write_text(
                json.dumps(
                    {
                        "passed": True,
                        "transport": "extension",
                        "headless": is_headless,
                        "snapshots": [v["state"] for v in snapshots],
                        "stopped": stopped,
                    }
                ),
                encoding="utf-8",
            )
    finally:
        await runner.cleanup()
