"""Existing personal Chrome -> explicit host attach -> handoff -> disconnect.

Uses the real installed fixture extension, worker HTTP server, native trusted
input and cookies. Both supported WebSocket backends run the same journey.
No user/developer profile is opened, copied or modified.
"""

import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
import time

import aiohttp
from aiohttp import web
import psutil
import pytest

from ai_dev_browser.core import js_evaluate, page_goto


@pytest.mark.parametrize(
    "_visibility",
    ["headless", pytest.param("headful", marks=pytest.mark.extension_native)],
)
async def test_existing_profile_worker_handoff_and_disconnect(
    live_extension, tmp_path, _visibility
):
    receipts = []
    nonce = secrets.token_hex(8)

    async def page(_request):
        return web.Response(
            text="""<!doctype html><meta charset="utf-8"><title>Existing profile</title>
<style>body{margin:0}input,button{position:absolute;left:30px;width:300px;height:40px}input{top:30px}button{top:100px}</style>
<input id="name"><button id="submit">Submit once</button>
<script>submit.onclick=event=>fetch('/receipt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:document.querySelector('#name').value,cookie:document.cookie,trusted:event.isTrusted})});</script>""",
            content_type="text/html",
        )

    async def receipt(request):
        receipts.append(await request.json())
        return web.json_response({"saved": True})

    site = web.Application()
    site.router.add_get("/", page)
    site.router.add_post("/receipt", receipt)
    runner = web.AppRunner(site)
    await runner.setup()
    listener = web.TCPSite(runner, "127.0.0.1", 0)
    await listener.start()
    site_port = listener._server.sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{site_port}/"
    await live_extension.call(page_goto, url=url)
    seeded = await live_extension.call(
        js_evaluate,
        expression=f"document.cookie='personal_login={nonce}; Path=/';document.cookie",
    )
    assert "personal_login=" + nonce in seeded["result"]
    lease_root = tmp_path / "shared-personal-leases"
    workers = []
    controller = "user-" + secrets.token_hex(16)

    async with aiohttp.ClientSession() as http:

        async def start_worker(name, *, is_recovery=False):
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            root = tmp_path / name
            root.mkdir(exist_ok=is_recovery)
            host_token, ai_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            env = dict(
                os.environ,
                AI_DEV_BROWSER_EXTENSION_BRIDGE_PORT=str(live_extension.port),
                AI_DEV_BROWSER_WORKER_HOST_TOKEN=host_token,
                AI_DEV_BROWSER_WORKER_AI_TOKEN=ai_token,
            )
            with (root / "worker.log").open("wb") as log:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "ai_dev_browser.remote.worker",
                    "--profile-root",
                    str(root),
                    "--port",
                    str(port),
                    "--existing-extension-root",
                    str(lease_root),
                    env=env,
                    stdout=log,
                    stderr=log,
                    **(
                        {"creationflags": subprocess.CREATE_NO_WINDOW}
                        if os.name == "nt"
                        else {}
                    ),
                )
            workers.append(process)
            origin = f"http://127.0.0.1:{port}"
            binding = {
                "orgId": "existing-fixture",
                "userId": "fixture-owner",
                "sessionId": name,
            }

            async def invoke(action, *, ai=False, expected=200):
                async with http.post(
                    origin + ("/agent" if ai else "/invoke"),
                    headers={
                        "Authorization": "Bearer " + (ai_token if ai else host_token)
                    },
                    json=action
                    if ai
                    else {
                        "controller": controller,
                        "binding": binding,
                        "action": action,
                    },
                ) as response:
                    body = await response.json()
                    assert response.status == expected, body
                    return body

            deadline = asyncio.get_running_loop().time() + 15
            while True:
                assert process.returncode is None, (
                    "The real worker exited during startup; see its owned log"
                )
                try:
                    initial = await invoke({"kind": "state"})
                    break
                except aiohttp.ClientConnectionError:
                    assert asyncio.get_running_loop().time() < deadline
                    await asyncio.sleep(0.05)
            assert initial["session"]["state"] == "stopped"
            assert initial["session"]["capabilities"]["existingExtension"] is True
            return invoke

        def epochs(reply):
            return {
                key: reply["session"][key] for key in ("controlEpoch", "targetEpoch")
            }

        try:
            first = await start_worker("first")
            selected = (await first({"kind": "inspect-existing-extension"}))[
                "existingExtension"
            ]
            assert selected and selected["sessionId"].startswith("extension-")
            assert selected["profileId"]
            # AI has no attachment capability; a host explicitly chooses it.
            await first(
                {"kind": "connect-existing-extension", **selected},
                ai=True,
                expected=409,
            )
            wrong_profile = await first(
                {
                    "kind": "connect-existing-extension",
                    **selected,
                    "profileId": selected["profileId"] + "-different",
                },
                expected=409,
            )
            assert wrong_profile["error"] == "browser_existing_extension_changed"
            attached = await first({"kind": "connect-existing-extension", **selected})
            state = attached["session"]
            assert state["state"] == "human" and state["isController"]
            assert state["browserSessionId"] == selected["sessionId"]
            assert state["profileId"] == "personal-" + selected["profileId"]
            assert state["personalExtension"] == {**selected, "isHeadless": None}
            assert not state["capabilities"]["authorizedPageLaunch"]
            rejected_review = await first(
                {
                    "kind": "open-authorized-page",
                    "url": url + "review/",
                    "cookie": {
                        "name": "fixture_review",
                        "value": secrets.token_hex(32),
                        "url": url + "review/",
                        "path": "/review/",
                        "httpOnly": True,
                        "sameSite": "Strict",
                        "expires": time.time() + 1800,
                    },
                    **epochs(attached),
                },
                expected=409,
            )
            assert rejected_review["error"] == "browser_authorized_page_not_supported"
            unchanged = (await first({"kind": "state"}))["session"]
            assert unchanged["activeTargetId"] == state["activeTargetId"]
            assert unchanged["targetEpoch"] == state["targetEpoch"]
            assert unchanged["tabs"] == state["tabs"]
            assert state["isHeadless"] is None, (
                "Unknown personal Chrome launch mode must not be invented"
            )
            assert (
                not state["capabilities"]["lifecycle"]
                and not state["capabilities"]["fileTransfer"]
            )
            second = await start_worker("second")
            conflict = await second(
                {"kind": "connect-existing-extension", **selected}, expected=409
            )
            assert conflict["error"] == "browser_existing_profile_in_use"
            blocked = await first(
                {
                    "kind": "input",
                    "input": {"kind": "text", "text": "bypass"},
                    **epochs(attached),
                },
                ai=True,
                expected=409,
            )
            assert blocked["error"] == "browser_control_held_by_user"
            await first(
                {
                    "kind": "restart",
                    "transport": "extension",
                    "isHeadless": True,
                    "acknowledgeStateLoss": True,
                    **epochs(attached),
                },
                expected=409,
            )
            await first(
                {
                    "kind": "input",
                    "input": {"kind": "click", "x": 80, "y": 50},
                    **epochs(attached),
                }
            )
            human = "Personal Chrome 中文 " + nonce
            await first(
                {
                    "kind": "input",
                    "input": {"kind": "text", "text": human},
                    **epochs(attached),
                }
            )
            returned = await first(
                {
                    "kind": "return",
                    "note": "Read the user's input before continuing",
                    **epochs(attached),
                }
            )
            assert returned["session"]["browserSessionId"] == state["browserSessionId"]
            assert returned["session"]["profileId"] == state["profileId"]
            inspected = await first(
                {
                    "kind": "command",
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": "JSON.stringify({value:document.querySelector('#name').value,cookie:document.cookie})",
                        "returnByValue": True,
                    },
                    **epochs(returned),
                },
                ai=True,
            )
            actual = json.loads(inspected["result"]["result"]["value"])
            assert (
                actual["value"] == human
                and "personal_login=" + nonce in actual["cookie"]
            )
            await first(
                {
                    "kind": "input",
                    "input": {"kind": "click", "x": 80, "y": 120},
                    **epochs(returned),
                },
                ai=True,
            )
            deadline = asyncio.get_running_loop().time() + 10
            while not receipts:
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.05)
            assert (
                len(receipts) == 1
                and receipts[0]["trusted"]
                and receipts[0]["value"] == human
            )
            assert "personal_login=" + nonce in receipts[0]["cookie"]
            held = await first({"kind": "take", **epochs(returned)})
            disconnected = await first(
                {"kind": "disconnect-existing-extension", **epochs(held)}
            )
            assert disconnected["session"]["state"] == "stopped"
            assert disconnected["session"]["personalExtension"] is None
            assert psutil.pid_exists(live_extension.chrome_pid), (
                "Disconnect stopped the user's Chrome"
            )
            still_open = await live_extension.call(
                js_evaluate, expression="document.querySelector('#name').value"
            )
            assert still_open["result"] == human
            # The same endpoint and identity can be explicitly selected by a
            # second conversation after the first releases its real OS lock.
            next_owner = await second(
                {"kind": "connect-existing-extension", **selected}
            )
            assert next_owner["session"]["profileId"] == state["profileId"]
            ai_owned = await second({"kind": "return", **epochs(next_owner)})
            assert ai_owned["session"]["state"] == "ai"
            # A real crash bypasses graceful disconnect. The saved AI lease
            # has no human controller; Chrome must survive and the restored
            # host must be able to explicitly disconnect its saved reference.
            crashed = workers[-1]
            crashed.kill()
            await asyncio.wait_for(crashed.wait(), 10)
            assert psutil.pid_exists(live_extension.chrome_pid)
            restored = await start_worker("second", is_recovery=True)
            recovered = await restored({"kind": "state"})
            assert (
                recovered["session"]["personalExtension"]["profileId"]
                == state["personalExtension"]["profileId"]
            )
            assert not recovered["session"]["isController"]
            stale = await restored(
                {"kind": "disconnect-existing-extension", **epochs(ai_owned)},
                expected=409,
            )
            assert stale["error"] == "stale_browser_operation"
            await restored(
                {
                    "kind": "connect-existing-extension",
                    **selected,
                    "sessionId": selected["sessionId"] + "-changed",
                },
                expected=409,
            )
            released = await restored(
                {"kind": "disconnect-existing-extension", **epochs(recovered)}
            )
            assert released["session"]["personalExtension"] is None
            assert released["session"]["isController"]
            assert psutil.pid_exists(live_extension.chrome_pid)
            after_crash = await live_extension.call(
                js_evaluate, expression="document.querySelector('#name').value"
            )
            assert after_crash["result"] == human
            evidence = {
                "workflow": "existing-personal-profile-handoff-disconnect",
                "passed": True,
                "actualChrome": True,
                "profileId": state["profileId"],
                "browserSessionId": state["browserSessionId"],
                "trustedUnicodeOnce": True,
                "cookiePreserved": True,
                "exclusiveConversationLease": True,
                "aiCannotAttach": True,
                "chromeAliveAfterDisconnect": psutil.pid_exists(
                    live_extension.chrome_pid
                ),
                "realWorkerCrashRecoveredWithoutClosingChrome": True,
            }
            (tmp_path / "existing-worker-evidence.json").write_text(
                json.dumps(evidence, indent=2), encoding="utf-8"
            )
        finally:
            for process in reversed(workers):
                if process.returncode is None:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), 10)
            await runner.cleanup()
