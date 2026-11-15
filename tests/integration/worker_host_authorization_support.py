"""Real Chrome + HTTP: queued host work must retain current authorization.

The authority provider is an explicit fixture. The HTTP Worker, browser,
trusted input, page, screenshot and file store are real. This does not certify
a production principal provider or a native atomic effect fence.
"""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
from urllib.parse import quote

import aiohttp
from aiohttp import web

from ai_dev_browser.remote.worker import Worker, application
from tests.integration.test_remote_view import wait_for
from tests.integration.test_worker_authorization_live import serve


async def host_journey(tmp_path, extension=None):
    receipts = []

    async def page(_request):
        return web.Response(
            text="""<!doctype html><meta charset=utf-8><title>Host review</title>
<style>body{margin:24px;font:20px sans-serif}input,button{display:block;margin:20px;width:300px;height:44px}</style>
<h1>Review request</h1><label>Request name<input id=name></label>
<button id=submit>Submit once</button><p id=done>Draft</p>
<script>window.inputs=[];const field=document.querySelector('#name');
field.oninput=e=>inputs.push({value:e.target.value,trusted:e.isTrusted});
document.querySelector('#submit').onclick=async e=>{
await fetch('/receipt',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({value:document.querySelector('#name').value,trusted:e.isTrusted})});
document.querySelector('#done').textContent='Request saved';};</script>""",
            content_type="text/html",
        )

    async def receipt(request):
        receipts.append(await request.json())
        return web.json_response({"saved": True})

    site = web.Application()
    site.router.add_get("/", page)
    site.router.add_get("/next", page)
    site.router.add_post("/receipt", receipt)
    website_runner, website = await serve(site)
    binding = {"orgId": "fixture", "userId": "human", "sessionId": "host-run"}
    controller = "user-host-fixture"
    host_token, ai_token = secrets.token_hex(24), secrets.token_hex(24)
    worker = Worker(
        tmp_path / "worker",
        host_token,
        ai_token,
        display_mode="native",
        chrome_path=os.environ.get("AI_DEV_BROWSER_CHROME"),
        chrome_args=["--no-sandbox"] if sys.platform == "linux" else [],
        existing_extension_root=tmp_path / "personal-leases" if extension else None,
        require_host_authorization=True,
    )
    allowed = True
    result = None
    resolved = asyncio.Event()
    actions = []
    checked = 0

    async def authorization(request, original_binding, original_controller, action):
        assert original_binding == binding and original_controller == controller
        actions.append(action["kind"])
        resolved.set()

        async def check():
            nonlocal checked
            checked += 1
            if not allowed:
                raise PermissionError("private fixture authority")
            return result

        return check

    runner, origin = await serve(application(worker, host_authorization=authorization))
    trace = []

    def epochs():
        return {
            "controlEpoch": worker.control.epoch,
            "targetEpoch": worker.control.target_epoch,
        }

    async with aiohttp.ClientSession(
        headers={"Authorization": "Bearer " + host_token},
        timeout=aiohttp.ClientTimeout(total=60),
    ) as http:

        async def host(action, error=None):
            async with http.post(
                origin + "/invoke",
                json={"binding": binding, "controller": controller, "action": action},
            ) as response:
                body = await response.json()
                trace.append(
                    {
                        "kind": action["kind"],
                        "status": response.status,
                        "error": body.get("error"),
                    }
                )
                if error:
                    assert response.status == 409 and body == {"error": error}, body
                else:
                    assert response.status == 200, body
                assert "private fixture" not in json.dumps(body)
                return body

        async def input_event(event, error=None):
            return await host({"kind": "input", "input": event, **epochs()}, error)

        async def click(selector):
            box = await driver.js(
                f"JSON.stringify((()=>{{let r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}}}})())"
            )
            await input_event({"kind": "click", **json.loads(box)})

        try:
            if extension:
                selected = (await host({"kind": "inspect-existing-extension"}))[
                    "existingExtension"
                ]
                await host({"kind": "connect-existing-extension", **selected})
            else:
                # A real launch waits for the lifecycle queue. Withdrawal must
                # prevent Chrome creation, rather than merely hide its reply.
                async with worker.lifecycle:
                    resolved.clear()
                    pending = asyncio.create_task(
                        host(
                            {"kind": "start", "isHeadless": True, "transport": "cdp"},
                            "browser_authorization_denied",
                        )
                    )
                    await asyncio.wait_for(resolved.wait(), 10)
                    allowed = False
                await pending
                assert worker.browser is None and worker.session is None
                allowed = True
                await host({"kind": "start", "isHeadless": True, "transport": "cdp"})
            identity = worker.browser["session_id"]
            await host({"kind": "navigate", "url": website + "/", **epochs()})
            driver = await worker.session._connect_page()  # Read-only oracle.
            await click("#name")
            await input_event({"kind": "text", "text": "original"})
            assert (
                await driver.js("document.querySelector('#name').value") == "original"
            )

            async with worker.control._operations:
                resolved.clear()
                pending = asyncio.create_task(
                    input_event(
                        {"kind": "text", "text": " REVOKED"},
                        "browser_authorization_denied",
                    )
                )
                await asyncio.wait_for(resolved.wait(), 10)
                allowed = False
            await pending
            assert await driver.js("inputs") == [{"value": "original", "trusted": True}]
            allowed = True

            # Delay a genuine browser layout read, then withdraw before input.
            # No fake CDP reply is used and no Input command may be submitted.
            dimensions = worker.session._dimensions
            arrived, release = asyncio.Event(), asyncio.Event()

            async def held_dimensions(page):
                value = await dimensions(page)
                arrived.set()
                await release.wait()
                return value

            worker.session._dimensions = held_dimensions
            try:
                pending = asyncio.create_task(
                    input_event(
                        {"kind": "text", "text": " AFTER LAYOUT"},
                        "browser_authorization_denied",
                    )
                )
                await asyncio.wait_for(arrived.wait(), 10)
                allowed = False
                release.set()
                await pending
            finally:
                release.set()
                worker.session._dimensions = dimensions
            assert await driver.js("inputs") == [{"value": "original", "trusted": True}]
            for malformed in (True, False, {"allowed": True}):
                allowed, result = True, malformed
                await input_event(
                    {"kind": "text", "text": " MALFORMED"},
                    "invalid_browser_authorization",
                )
            result = None
            await input_event({"kind": "text", "text": " + resumed"})
            await click("#submit")
            await wait_for(
                lambda: driver.js("document.querySelector('#done').textContent"),
                lambda value: value == "Request saved",
            )
            assert receipts == [{"value": "original + resumed", "trusted": True}]
            assert all(item["trusted"] for item in await driver.js("inputs"))

            await host({"kind": "attach", "viewerId": "review", "surface": "page"})
            frame = (await host({"kind": "frame", "viewerId": "review", **epochs()}))[
                "frame"
            ]
            (tmp_path / "host-authorized-accepted.jpg").write_bytes(
                base64.b64decode(frame["data"])
            )

            # The actual history read must not be used to navigate after revoke.
            await host({"kind": "navigate", "url": website + "/next", **epochs()})
            original_call = driver.call
            arrived, release = asyncio.Event(), asyncio.Event()

            async def held_history(method, *args, **kwargs):
                value = await original_call(method, *args, **kwargs)
                if method == "Page.getNavigationHistory":
                    arrived.set()
                    await release.wait()
                return value

            driver.call = held_history
            try:
                pending = asyncio.create_task(
                    host({"kind": "back", **epochs()}, "browser_authorization_denied")
                )
                await asyncio.wait_for(arrived.wait(), 10)
                allowed = False
                release.set()
                await pending
            finally:
                release.set()
                driver.call = original_call
            assert await driver.js("location.pathname") == "/next"
            allowed = True
            await host({"kind": "back", **epochs()})
            await wait_for(
                lambda: driver.js("location.pathname"), lambda value: value == "/"
            )
            assert len(receipts) == 1 and worker.browser["session_id"] == identity

            if not extension:
                # File bytes are real HTTP streaming input. Revoke while a
                # later chunk is held; neither file nor index may be created.
                sent, release_body = asyncio.Event(), asyncio.Event()

                async def body():
                    yield b"first chunk"
                    sent.set()
                    await release_body.wait()
                    yield b"second chunk"

                context = {"binding": binding, "controller": controller, **epochs()}
                headers = {
                    "X-ADB-Browser-Context": quote(json.dumps(context)),
                    "X-ADB-Browser-File-Name": "review.txt",
                }
                before = list(worker.files.uploads.iterdir())
                pending = asyncio.ensure_future(
                    http.post(origin + "/files/receive", headers=headers, data=body())
                )
                await asyncio.wait_for(sent.wait(), 10)
                allowed = False
                release_body.set()
                async with await pending as response:
                    assert response.status == 409
                    assert (await response.json())[
                        "error"
                    ] == "browser_authorization_denied"
                assert list(worker.files.uploads.iterdir()) == before
                allowed = True
                data = b"reviewed payload"
                async with http.post(
                    origin + "/files/receive", headers=headers, data=data
                ) as response:
                    uploaded = (await response.json())["file"]
                    assert response.status == 200
                assert uploaded["sha256"] == hashlib.sha256(data).hexdigest()
                assert (
                    worker.files.path(uploaded["id"], kind="upload").read_bytes()
                    == data
                )

            (tmp_path / "host-authorization-evidence.json").write_text(
                json.dumps(
                    {
                        "transport": "extension" if extension else "cdp",
                        "trace": trace,
                        "receipts": receipts,
                        "currentAssertions": checked,
                        "authorizedActions": actions,
                        "sameBrowser": worker.browser["session_id"] == identity,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            if extension:
                await host({"kind": "disconnect-existing-extension", **epochs()})
            else:
                await host({"kind": "stop", **epochs()})
            assert worker.browser is None and worker.session is None
        finally:
            allowed = True
            await runner.cleanup()
            await website_runner.cleanup()


async def extension_host_journey(live_extension, tmp_path):
    # The bridge port is an import-time configuration contract. Exercise it in
    # a fresh normal process rather than replacing production connection APIs.
    env = dict(
        os.environ, AI_DEV_BROWSER_EXTENSION_BRIDGE_PORT=str(live_extension.port)
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import asyncio,sys;from pathlib import Path;"
        "from tests.integration.worker_host_authorization_support import host_journey;"
        "asyncio.run(host_journey(Path(sys.argv[1]), extension=True))",
        str(tmp_path),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 90)
        (tmp_path / "host-worker-child.log").write_bytes(output)
        assert process.returncode == 0, output.decode("utf-8", errors="replace")
        evidence = json.loads(
            (tmp_path / "host-authorization-evidence.json").read_text(encoding="utf-8")
        )
        assert evidence["sameBrowser"] and evidence["transport"] == "extension"
        assert evidence["receipts"] == [
            {"value": "original + resumed", "trusted": True}
        ]
    finally:
        if process.returncode is None:
            process.terminate()
            await asyncio.wait_for(process.wait(), 10)
