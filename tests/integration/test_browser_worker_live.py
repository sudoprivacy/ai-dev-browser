"""The public host/AI worker uses one real browser in both native modes."""

import asyncio
import json
from pathlib import Path
import secrets
import sys
import time

import aiohttp
import pytest
from aiohttp import web

from ai_dev_browser.remote.worker import Worker, application
from tests.integration.test_remote_view import wait_for

pytest_plugins = ["tests.integration.test_remote_view"]


@pytest.mark.parametrize("transport", ["cdp", "extension"])
async def test_host_authorized_page_keeps_cookie_private_and_preserves_control(
    tmp_path,
    transport,
):
    """The actual host route installs the cookie before the first protected read."""
    extension = Path("/opt/browser/extension")
    if transport == "extension" and not (extension / "identity.json").is_file():
        pytest.skip("Signed managed extension policy fixture required")
    credential = secrets.token_hex(32)
    reads = []
    reload_arrived = asyncio.Event()
    release_reload = asyncio.Event()
    app = web.Application()

    async def review(request):
        if reads:
            reload_arrived.set()
            await release_reload.wait()
        reads.append(request.cookies.get("fixture_review"))
        if reads[-1] != credential:
            raise web.HTTPForbidden()
        return web.Response(
            text=(
                "<title>Private review</title>"
                f'<p id="review" data-visit="{len(reads)}">Checked model</p>'
            ),
            content_type="text/html",
        )

    app.router.add_get("/review/fixture/", review)

    async def unavailable(_request):
        return web.json_response({"error": "VIEW_UNAVAILABLE"}, status=503)

    app.router.add_get("/review/error/", unavailable)
    review_runner = web.AppRunner(app)
    await review_runner.setup()
    review_site = web.TCPSite(review_runner, "127.0.0.1", 0)
    await review_site.start()
    url = f"http://127.0.0.1:{review_site._server.sockets[0].getsockname()[1]}/review/fixture/"
    host_token, ai_token = secrets.token_hex(32), secrets.token_hex(32)
    worker = Worker(
        tmp_path,
        host_token,
        ai_token,
        display_mode="native",
        extension_directory=extension if transport == "extension" else None,
        chrome_args=["--no-sandbox"] if sys.platform == "linux" else [],
    )
    runner = web.AppRunner(application(worker))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8080 if transport == "extension" else 0)
    await site.start()
    origin = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    binding = {"orgId": "local", "userId": "fixture", "sessionId": "review-chat"}
    controller = "user-fixture-controller"
    async with aiohttp.ClientSession() as http:

        async def host(action, *, token=host_token, owner=controller, status=200):
            async with http.post(
                origin + "/invoke",
                headers={"Authorization": "Bearer " + token},
                json={"binding": binding, "controller": owner, "action": action},
            ) as response:
                if status == 403:
                    assert response.status == status
                    return None
                body = await response.json()
                assert response.status == status, body
                return body

        try:
            started = (
                await host(
                    {"kind": "start", "isHeadless": True, "transport": transport}
                )
            )["session"]
            assert started["capabilities"]["authorizedPageLaunch"]
            action = {
                "kind": "open-authorized-page",
                "url": url,
                "controlEpoch": started["controlEpoch"],
                "targetEpoch": started["targetEpoch"],
                "cookie": {
                    "name": "fixture_review",
                    "value": credential,
                    "url": url,
                    "path": "/review/fixture/",
                    "httpOnly": True,
                    "sameSite": "Strict",
                    "expires": time.time() + 1800,
                },
            }
            await host(action, token=ai_token, status=403)
            other = await host(action, owner="user-other", status=409)
            assert other["error"] == "browser_control_not_owned"
            assert not reads
            result = await host(action)
            current = result["session"]
            assert reads == [credential]
            assert current["browserSessionId"] == started["browserSessionId"]
            assert current["activeTargetId"] != started["activeTargetId"]
            assert current["state"] == "human" and current["isController"]
            assert current["targetEpoch"] > started["targetEpoch"]
            assert credential not in json.dumps(result)
            assert credential not in (tmp_path / "control.json").read_text()
            page = await worker.session._connect_page()
            assert await page.js("document.title") == "Private review"
            assert credential not in await page.js("document.cookie")
            stale = await host(action, status=409)
            assert stale["error"] == "stale_browser_operation"
            assert reads == [credential]
            async with http.post(
                origin + "/agent",
                headers={"Authorization": "Bearer " + ai_token},
                json={**action, "targetEpoch": current["targetEpoch"]},
            ) as response:
                assert response.status == 409
                assert (await response.json())[
                    "error"
                ] == "invalid_agent_browser_action"
            failed_url = url.replace("/review/fixture/", "/review/error/")
            failed = await host(
                {
                    **action,
                    "url": failed_url,
                    "targetEpoch": current["targetEpoch"],
                    "cookie": {
                        **action["cookie"],
                        "url": failed_url,
                        "path": "/review/error/",
                    },
                },
                status=409,
            )
            assert failed["error"] == "browser_authorized_page_failed"
            restored = (await host({"kind": "state"}))["session"]
            assert restored["activeTargetId"] == current["activeTargetId"]
            page = await worker.session._connect_page()
            cookies = await page.call("Network.getCookies", {"urls": [failed_url]})
            assert not cookies["cookies"]
            reloaded = await host(
                {
                    "kind": "reload",
                    "controlEpoch": restored["controlEpoch"],
                    "targetEpoch": restored["targetEpoch"],
                }
            )
            assert (
                reloaded["session"]["browserSessionId"] == current["browserSessionId"]
            )
            # Reload acknowledges dispatch before its HTTP response arrives.
            # Hold that response to expose the old no-loader wait deterministically.
            await asyncio.wait_for(reload_arrived.wait(), 15)
            assert reads == [credential]
            release_reload.set()
            observed = await wait_for(
                lambda: page.js(
                    "({title:document.title,visit:"
                    "document.querySelector('#review')?.dataset.visit})"
                ),
                lambda value: value == {"title": "Private review", "visit": "2"},
            )
            assert observed == {"title": "Private review", "visit": "2"}
            assert reads == [credential, credential]
        finally:
            release_reload.set()
            await worker.close()
            await runner.cleanup()
            await review_runner.cleanup()


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
            # The chat, independent viewer and status poller read concurrently.
            # Reading status must preserve the human's interactive page.
            idle_reads = await asyncio.gather(
                *(host({"kind": "state"}) for _ in range(8))
            )
            assert all(value["session"]["state"] == "human" for value in idle_reads)
            assert all(
                value["session"]["capabilities"]["pageView"] for value in idle_reads
            )
            assert all(
                value["session"]["activeTargetId"] == held["activeTargetId"]
                for value in idle_reads
            )
            # Files are enabled on the worker. A native dialog must still be
            # answerable without an upload-configuration command blocking it.
            await host({"kind": "return", **epochs(held)})
            ready = (await host({"kind": "state"}))["session"]
            await agent(
                {
                    "kind": "command",
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": "setTimeout(()=>{window.reviewResult=confirm('Review with files enabled')},50);true",
                        "returnByValue": True,
                    },
                    **epochs(ready),
                }
            )
            held = (await host({"kind": "take", **epochs(ready)}))["session"]
            deadline = asyncio.get_running_loop().time() + 10
            while not (await host({"kind": "state"}))["session"]["dialog"]:
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.05)
            await host(
                {
                    "kind": "input",
                    "input": {"kind": "dialog", "accept": True},
                    **epochs(held),
                }
            )
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
            held = (await host({"kind": "take", **epochs(fresh)}))["session"]
            stopping = asyncio.create_task(host({"kind": "stop", **epochs(held)}))
            snapshots = []
            while not stopping.done():
                snapshots.append((await host({"kind": "state"}))["session"])
            stopped = (await stopping)["session"]
            assert snapshots
            assert all(
                value["state"] in ("human", "pausing", "stopped") for value in snapshots
            )
            assert all(value["isHumanControlHeld"] for value in snapshots)
            assert (
                stopped["state"] == "stopped"
                and stopped["profileId"] == fresh["profileId"]
            )
        finally:
            await runner.cleanup()
