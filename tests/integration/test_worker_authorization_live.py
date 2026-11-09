"""Real MCP/Chrome effect boundaries with explicitly synthetic host grants.

These qualify the public embedding hook, not a production identity provider,
native atomic fence, physical phone or managed SudoCode model journey.
"""

import asyncio
import json
import os
import secrets
import sys
from contextlib import asynccontextmanager

import aiohttp
import pytest
from aiohttp import web

from ai_dev_browser.remote.worker import Worker, application

pytestmark = pytest.mark.asyncio


async def serve(app):
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"


class FixtureGrants:
    def __init__(self):
        self.allowed = {"native-main": True, "native-child": True}
        self.result = None
        self.resolved = asyncio.Event()
        self.checking = asyncio.Event()
        self.release = asyncio.Event()
        self.pause = False
        self.checked = []
        self.restart_checks = 0
        self.revoke_after_stop = False
        self.pause_factory = False
        self.factory_release = asyncio.Event()

    async def resolve(self, request, action):
        # Synthetic server authentication only. No actor from tool arguments.
        actor = request.headers.get("X-Fixture-Invocation")
        if actor not in self.allowed:
            raise PermissionError("private fixture credential")
        kind = action["kind"]
        self.resolved.set()
        if self.pause_factory:
            await self.factory_release.wait()

        async def check():
            self.checked.append((actor, kind))
            self.checking.set()
            if self.pause:
                await self.release.wait()
            if kind == "restart":
                self.restart_checks += 1
                if self.revoke_after_stop and self.restart_checks == 2:
                    self.allowed[actor] = False
            if not self.allowed[actor]:
                raise PermissionError("private fixture grant details")
            return self.result

        return check


@asynccontextmanager
async def fixture(tmp_path, grants=None):
    async def page(_request):
        return web.Response(
            text="<title>Original draft</title><textarea id=draft></textarea>",
            content_type="text/html",
        )

    website = web.Application()
    website.router.add_get("/", page)
    website_runner, website_origin = await serve(website)
    host_token, ai_token = secrets.token_hex(24), secrets.token_hex(24)
    worker = Worker(
        tmp_path / "original-profile",
        host_token,
        ai_token,
        chrome_path=os.environ.get("AI_DEV_BROWSER_CHROME"),
        chrome_args=["--no-sandbox"] if sys.platform == "linux" else [],
        display_mode="native",
        require_agent_authorization=True,
    )
    runner, origin = await serve(
        application(worker, agent_authorization=grants.resolve if grants else None)
    )
    binding = {
        "orgId": "fixture-org",
        "userId": "fixture-human",
        "sessionId": "browser-only",
    }
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as http:

        async def host(action):
            async with http.post(
                origin + "/invoke",
                headers={"Authorization": "Bearer " + host_token},
                json={
                    "binding": binding,
                    "controller": "user-fixture",
                    "action": action,
                },
            ) as response:
                body = await response.json()
                assert response.status == 200, body.get("error")
                return body

        async def mcp(name, arguments, *, actor="native-main", error=None):
            async with http.post(
                origin + "/mcp",
                headers={
                    "Authorization": "Bearer " + ai_token,
                    "X-Fixture-Invocation": actor,
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
            ) as response:
                body = await response.json()
                assert response.status == 200
                result = body["result"]
                text = result["content"][0]["text"]
                if error:
                    assert result.get("isError") is True
                    assert error in text
                    assert "private fixture" not in text
                    return None
                assert not result.get("isError"), text
                return json.loads(text)

        async def agent(action, error=None, *, actor=None):
            async with http.post(
                origin + "/agent",
                headers={
                    "Authorization": "Bearer " + ai_token,
                    **({"X-Fixture-Invocation": actor} if actor else {}),
                },
                json=action,
            ) as response:
                body = await response.json()
                if error:
                    assert response.status == 409 and body["error"] == error
                    return None
                assert response.status == 200, body
                return body

        try:
            await host(
                {"kind": "state"}
            )  # Publish browser binding; no Agent/chat is created.
            yield worker, host, mcp, agent, website_origin
        finally:
            if grants:
                grants.release.set()
                grants.factory_release.set()
            await runner.cleanup()
            await website_runner.cleanup()


def epochs(worker):
    return {
        "controlEpoch": worker.control.epoch,
        "targetEpoch": worker.control.target_epoch,
    }


def insert(worker, text):
    return {
        "kind": "command",
        "method": "Input.insertText",
        "paramsJson": json.dumps({"text": text}),
        **epochs(worker),
    }


async def test_real_mcp_rechecks_grant_after_wait_and_stop_then_resumes_same_draft(
    tmp_path,
):
    grants = FixtureGrants()
    async with fixture(tmp_path, grants) as (worker, host, mcp, agent, website):
        await agent({"kind": "state"}, "browser_authorization_denied")
        # Launch authorization must run after waiting for lifecycle ownership.
        async with worker.lifecycle:
            launch = asyncio.create_task(
                mcp(
                    "browser_launch",
                    {"isHeadless": True, "transport": "cdp"},
                    error="browser_authorization_denied",
                )
            )
            await asyncio.wait_for(grants.resolved.wait(), 10)
            assert grants.checked == []
            grants.allowed["native-main"] = False
        await launch
        assert worker.browser is None
        grants.allowed["native-main"] = True
        await mcp("browser_launch", {"isHeadless": True, "transport": "cdp"})
        original = worker.browser
        await mcp(
            "browser_action",
            {"kind": "navigate", "url": website + "/", **epochs(worker)},
        )
        await mcp(
            "browser_action",
            {
                "kind": "command",
                "method": "Runtime.evaluate",
                "paramsJson": json.dumps({"expression": "draft.focus()"}),
                **epochs(worker),
            },
        )
        await mcp("browser_action", insert(worker, "original"))
        page = await worker.session._connect_page()  # Read-only browser oracle.
        assert await page.js("draft.value") == "original"

        # An earlier input owns the actual public barrier; no eager guard pass.
        grants.resolved.clear()
        before = len(grants.checked)
        async with worker.control._operations:
            queued = asyncio.create_task(
                mcp(
                    "browser_action",
                    insert(worker, " REVOKED"),
                    error="browser_authorization_denied",
                )
            )
            await asyncio.wait_for(grants.resolved.wait(), 10)
            assert len(grants.checked) == before
            grants.allowed["native-main"] = False
        await queued
        assert await page.js("draft.value") == "original"
        await mcp("browser_observe", {}, error="browser_authorization_denied")
        await mcp("browser_stop", epochs(worker), error="browser_authorization_denied")
        assert worker.browser is original

        grants.allowed["native-main"] = True
        for malformed in (False, True, {"allowed": False}):
            grants.result = malformed
            await mcp(
                "browser_action",
                insert(worker, " MALFORMED"),
                error="invalid_browser_authorization",
            )
        grants.result = None
        assert await page.js("draft.value") == "original"

        # Native Stop starts while the authorization callback owns the barrier.
        grants.pause = True
        grants.checking.clear()
        pending = asyncio.create_task(
            mcp(
                "browser_action",
                insert(worker, " INTERRUPTED"),
                error="stale_browser_operation",
            )
        )
        await asyncio.wait_for(grants.checking.wait(), 10)
        take = asyncio.create_task(host({"kind": "take", **epochs(worker)}))

        async def pausing():
            while worker.control.state != "pausing":
                await asyncio.sleep(0)

        await asyncio.wait_for(pausing(), 10)
        grants.release.set()
        await pending
        await take
        grants.pause = False
        assert await page.js("draft.value") == "original"
        await host(
            {
                "kind": "input",
                "input": {"kind": "text", "text": " + human"},
                **epochs(worker),
            }
        )
        await host({"kind": "return", **epochs(worker)})
        await mcp("browser_action", insert(worker, " + child"), actor="native-child")
        assert worker.browser is original
        assert await page.js("draft.value") == "original + human + child"
        assert ("native-child", "command") in grants.checked
        await mcp("browser_stop", epochs(worker))
        assert worker.browser is None and worker.session is None


async def test_missing_native_guard_refuses_ai_but_human_view_needs_no_agent(tmp_path):
    async with fixture(tmp_path) as (worker, host, mcp, agent, website):
        launch = {"kind": "start", "transport": "cdp", "isHeadless": True}
        await mcp("browser_launch", launch, error="browser_authorization_required")
        await agent(launch, "browser_authorization_required")
        assert worker.browser is None
        # Existing authenticated host/human flow is independent of a native Agent.
        await host(launch)
        await host({"kind": "navigate", "url": website + "/", **epochs(worker)})
        page = await worker.session._connect_page()  # Read-only oracle.
        assert await page.js("document.title") == "Original draft"
        await host({"kind": "stop", **epochs(worker)})
        assert worker.browser is None


async def test_restart_rechecks_after_stop_before_replacement_launch(tmp_path):
    grants = FixtureGrants()
    async with fixture(tmp_path, grants) as (worker, _host, mcp, _agent, _website):
        await mcp("browser_launch", {"isHeadless": True, "transport": "cdp"})
        first = worker.browser
        await mcp(
            "browser_restart",
            {
                "isHeadless": True,
                "transport": "cdp",
                "acknowledgeStateLoss": True,
                **epochs(worker),
            },
        )
        assert worker.browser is not first and worker.browser is not None
        grants.restart_checks = 0
        grants.revoke_after_stop = True
        await mcp(
            "browser_restart",
            {
                "isHeadless": True,
                "transport": "cdp",
                "acknowledgeStateLoss": True,
                **epochs(worker),
            },
            error="browser_authorization_denied",
        )
        assert grants.restart_checks == 2
        assert worker.browser is None and worker.session is None


async def test_factory_wait_cannot_move_an_old_call_to_rebound_browser(tmp_path):
    grants = FixtureGrants()
    grants.pause_factory = True
    async with fixture(tmp_path, grants) as (worker, _host, mcp, _agent, _website):
        pending = asyncio.create_task(
            mcp(
                "browser_launch",
                {"isHeadless": True, "transport": "cdp"},
                error="browser_authorization_denied",
            )
        )
        await asyncio.wait_for(grants.resolved.wait(), 10)
        original = worker.binding.copy()
        changed = {**original, "sessionId": "different-browser-session"}
        await worker.rebind(changed, original["sessionId"], "user-fixture")
        grants.factory_release.set()
        await pending
        assert worker.binding == changed
        assert worker.browser is None and grants.checked == []


async def test_observe_discovers_remaining_real_tab_after_external_close(tmp_path):
    grants = FixtureGrants()
    async with fixture(tmp_path, grants) as (worker, _host, mcp, agent, website):
        await mcp("browser_launch", {"isHeadless": True, "transport": "cdp"})
        await mcp("browser_action", {"kind": "new-tab", **epochs(worker)})
        await mcp(
            "browser_action",
            {"kind": "navigate", "url": website + "/", **epochs(worker)},
        )
        previous = worker.session.target_id
        state = await agent({"kind": "state"}, actor="native-main")
        assert state["session"]["activeTargetId"] == previous
        # Simulate the separate native Chrome lifecycle, such as a person
        # closing its tab. This is a real isolated-browser action outside the
        # viewer/tool surface; assertions and subsequent input still use MCP.
        browser = await worker.session._connect_browser()
        await browser.call("Target.closeTarget", {"targetId": previous})
        observed = await mcp("browser_observe", {})
        assert observed["session"]["activeTargetId"] != previous
        await mcp(
            "browser_action",
            {"kind": "navigate", "url": website + "/", **epochs(worker)},
        )
        page = await worker.session._connect_page()  # Read-only oracle.
        assert await page.js("document.title") == "Original draft"
        await mcp("browser_stop", epochs(worker))
