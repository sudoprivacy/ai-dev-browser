"""Authenticated MCP commands share the selected tab's real child frames."""

import json
import os
from pathlib import Path
import secrets

import aiohttp
from aiohttp import web
import pytest

from ai_dev_browser.core import js_evaluate
from ai_dev_browser.remote.worker import Worker, application
from .test_extension_frames_live import owned_frame_id, wait_value

pytest_plugins = ["tests.integration.test_extension_frames_live"]


async def child_heading(tab):
    return (
        await js_evaluate(
            tab,
            "document.querySelector('#heading')?.textContent ?? null",
            frame="//child.test:",
        )
    )["result"]


@pytest.mark.parametrize("transport", ["cdp", "extension"])
async def test_worker_mcp_child_frames_keep_target_and_control(
    tmp_path, frame_site, transport
):
    extension = Path("/opt/browser/extension")
    if transport == "extension" and not (extension / "identity.json").is_file():
        pytest.skip("Signed managed Chrome fixture required")
    proof = {"passed": False, "transport": transport, "actualHttpMcp": True}
    host_token, ai_token = secrets.token_hex(32), secrets.token_hex(32)
    worker = Worker(
        tmp_path / "worker",
        host_token,
        ai_token,
        display_mode="native",
        extension_directory=extension if transport == "extension" else None,
        chrome_args=[
            "--host-resolver-rules=MAP *.test 127.0.0.1",
            "--proxy-server=direct://",
            *(["--no-sandbox"] if os.name != "nt" else []),
        ],
    )
    runner = web.AppRunner(application(worker))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8080 if transport == "extension" else 0)
    await site.start()
    origin = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    binding = {"orgId": "frame-fixture", "userId": "owner", "sessionId": "frame-review"}

    def epochs(state):
        return {key: state[key] for key in ("controlEpoch", "targetEpoch")}

    async with aiohttp.ClientSession() as http:

        async def host(action):
            async with http.post(
                origin + "/invoke",
                headers={"Authorization": "Bearer " + host_token},
                json={
                    "binding": binding,
                    "controller": "user-frame-owner",
                    "action": action,
                },
            ) as response:
                value = await response.json()
                assert response.status == 200, (response.status, value)
                return value["session"]

        async def agent(action):
            async with http.post(
                origin + "/agent",
                headers={"Authorization": "Bearer " + ai_token},
                json=action,
            ) as response:
                value = await response.json()
                assert response.status == 200, (response.status, value)
                return value["session"]

        async def command(state, method, params, frame=None, *, error=None):
            arguments = {
                "kind": "command",
                "method": method,
                "paramsJson": json.dumps(params),
                **epochs(state),
            }
            if frame is not None:
                arguments["frame"] = frame
            async with http.post(
                origin + "/mcp",
                headers={
                    "Authorization": "Bearer " + ai_token,
                    "X-ADB-Browser-Session": binding["sessionId"],
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "browser_action", "arguments": arguments},
                },
            ) as response:
                value = await response.json()
                assert response.status == 200, (response.status, value)
                result = value["result"]
                if error:
                    assert (
                        result.get("isError") and result["content"][0]["text"] == error
                    ), result
                    return None
                assert not result.get("isError"), result
                return json.loads(result["content"][0]["text"])["result"]

        async def read(state, expression, frame=None, **options):
            result = await command(
                state,
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True},
                frame,
                **options,
            )
            return result["result"].get("value") if result else None

        try:
            await host({"kind": "state"})
            state = await agent(
                {"kind": "start", "isHeadless": True, "transport": transport}
            )
            async with http.post(
                origin + "/mcp",
                headers={"Authorization": "Bearer " + ai_token},
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            ) as response:
                tools = (await response.json())["result"]["tools"]
                tool = next(tool for tool in tools if tool["name"] == "browser_action")
                assert "frame" in tool["inputSchema"]["properties"]
            state = await agent(
                {
                    "kind": "navigate",
                    "url": f"http://parent.test:{frame_site}/parent/first",
                    **epochs(state),
                }
            )
            first_id = state["activeTargetId"]
            first = next(
                tab
                for tab in worker.session.browser.tabs
                if str(tab.target.target_id) == first_id
            )
            await wait_value(lambda: child_heading(first), "Child first")
            expression = "document.querySelector('#heading')?.textContent ?? null"
            assert await read(state, expression) is None
            assert await read(state, expression, "//child.test:") == "Child first"
            assert (
                await read(state, "nested.textContent", "grandchild.test")
                == "nested-first"
            )
            first_frame = await owned_frame_id(first)
            # Real review pages put a large source document in an iframe
            # attribute. Native DOM events include the attribute even when a
            # command's result is tiny; every socket must retain its connection.
            assert (
                await read(
                    state,
                    "(()=>{document.querySelector('#review').setAttribute('data-review-fixture','x'.repeat(5*1024*1024));return true})()",
                )
                is True
            )
            assert await read(state, expression, first_frame) == "Child first"
            proof["largeParentDomEventPreserved"] = True
            large = await read(state, "'x'.repeat(5*1024*1024)")
            assert isinstance(large, str)
            assert len(large) == 5 * 1024 * 1024
            assert large.count("x") == len(large)
            del large
            proof["largeCommandReplyPreserved"] = True
            await read(state, "document.querySelector('#value').focus()", first_frame)
            text = "MCP \u4e2d\u6587"
            await command(state, "Input.insertText", {"text": text}, first_frame)
            assert await read(state, "value.value", first_frame) == text
            assert await read(state, "trust", first_frame) == [True]
            await command(
                state,
                "DOM.querySelector",
                {"nodeId": -999999, "selector": "#value"},
                first_frame,
                error="operation_failed",
            )
            await command(
                state,
                "Target.getTargets",
                {},
                first_frame,
                error="invalid_browser_command",
            )
            state = await agent({"kind": "new-tab", **epochs(state)})
            state = await agent(
                {
                    "kind": "navigate",
                    "url": f"http://parent.test:{frame_site}/parent/second",
                    **epochs(state),
                }
            )
            second_id = state["activeTargetId"]
            second = next(
                tab
                for tab in worker.session.browser.tabs
                if str(tab.target.target_id) == second_id
            )
            await wait_value(lambda: child_heading(second), "Child second")
            assert await read(state, expression, "//child.test:") == "Child second"
            assert await read(state, "value.value", "//child.test:") == ""
            await read(state, expression, first_frame, error="invalid_browser_frame")
            await read(state, expression, "child.test", error="invalid_browser_frame")
            await read(state, expression, [], error="invalid_browser_frame")
            old = state
            state = await agent(
                {"kind": "select-tab", "targetId": first_id, **epochs(state)}
            )
            await read(old, expression, first_frame, error="stale_browser_operation")
            assert await read(state, "value.value", first_frame) == text
            state = await host({"kind": "take", **epochs(state)})
            await read(
                state,
                "value.value='unexpected'",
                first_frame,
                error="browser_control_held_by_user",
            )
            state = await host({"kind": "return", **epochs(state)})
            assert await read(state, "value.value", first_frame) == text
            proof.update(
                passed=True,
                nestedFrameRead=True,
                trustedChineseInput=True,
                selectedTabScoped=True,
                foreignFrameRefused=True,
                ambiguousFrameRefused=True,
                malformedFrameRefused=True,
                staleTargetRefused=True,
                humanLeaseBlocksFrameWrites=True,
                resumedFrameValuePreserved=True,
            )
        finally:
            await runner.cleanup()
            proof["ownedBrowserStopped"] = worker.browser is None
            (tmp_path / "worker-frame-receipt.json").write_text(
                json.dumps(proof, indent=2), encoding="utf8"
            )
