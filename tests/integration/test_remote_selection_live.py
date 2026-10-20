"""Real remote selection and paste; application/graph acceptance stays separate."""

import asyncio
import json
from pathlib import Path
import secrets
import sys

import aiohttp
import pytest
from aiohttp import web

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.remote.page import PageView
from ai_dev_browser.remote.worker import Worker, application
from tests.integration.test_remote_view import (
    connect_page,
    navigate_owned_browser,
    wait_for,
)

pytest_plugins = ["tests.integration.test_remote_view"]

PHRASE = "CANONICAL_REVIEW_PHRASE"
RANGE = """(() => {
    const node = document.querySelector('#phrase').firstChild;
    const range = new Range(); range.setStart(node, 6); range.setEnd(node, 29);
    const rect = range.getBoundingClientRect();
    return [{x:rect.left+0.5,y:rect.top+rect.height/2},
        {x:rect.right-0.5,y:rect.top+rect.height/2}];
})()"""


@pytest.mark.parametrize(
    "is_headless,display_mode,transport",
    [
        (True, "native", "cdp"),
        (False, "native", "cdp"),
        pytest.param(
            False,
            "x11",
            "cdp",
            marks=pytest.mark.skipif(
                sys.platform != "linux",
                reason="Isolated X11 window view requires Linux",
            ),
        ),
        *[
            pytest.param(
                headless,
                mode,
                "extension",
                marks=pytest.mark.skipif(
                    not Path("/opt/browser/extension/identity.json").is_file(),
                    reason="Signed managed extension policy fixture required",
                ),
            )
            for headless, mode in ((True, "native"), (False, "x11"))
        ],
    ],
)
async def test_worker_selection_paste_and_lease(
    remote_site, tmp_path, is_headless, display_mode, transport
):
    """Select exact words -> copy -> Unicode multiline paste -> reject stale copy."""
    token = secrets.token_hex(32)
    worker = Worker(
        tmp_path,
        token,
        secrets.token_hex(32),
        display_mode=display_mode,
        extension_directory=Path("/opt/browser/extension")
        if transport == "extension"
        else None,
        chrome_args=["--no-sandbox"] if sys.platform == "linux" else [],
    )
    runner = web.AppRunner(application(worker))
    await runner.setup()
    # Match the signed fixture's Chrome policy update URL. A random port can
    # serve the worker API but cannot install that existing policy's CRX.
    site = web.TCPSite(runner, "127.0.0.1", 8080 if transport == "extension" else 0)
    await site.start()
    url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    binding = {"orgId": "local", "userId": "selection-fixture", "sessionId": "review"}
    controller = "user-selection-fixture"
    async with aiohttp.ClientSession() as http:

        async def host(action, status=200, actor=controller):
            async with http.post(
                url + "/invoke",
                headers={"Authorization": "Bearer " + token},
                json={"binding": binding, "controller": actor, "action": action},
            ) as response:
                body = await response.json()
                assert response.status == status, body
                return body

        def epochs(state):
            return {key: state[key] for key in ("controlEpoch", "targetEpoch")}

        async def input_event(event, state):
            if display_mode == "x11":
                offset = await (await worker.session._connect_page()).js("""({
                    x:screenX+(outerWidth-innerWidth)/2,
                    y:screenY+outerHeight-innerHeight-(outerWidth-innerWidth)/2})""")
                event = {**event}
                if event["kind"] == "drag":
                    event["points"] = [
                        {"x": p["x"] + offset["x"], "y": p["y"] + offset["y"]}
                        for p in event["points"]
                    ]
                elif event["kind"] == "click":
                    event["x"] += offset["x"]
                    event["y"] += offset["y"]
            return await host(
                {
                    "kind": "input",
                    "surface": "window" if display_mode == "x11" else "page",
                    "input": event,
                    **epochs(state),
                }
            )

        try:
            await host({"kind": "state"})
            await worker.agent(
                {"kind": "start", "isHeadless": is_headless, "transport": transport}
            )
            state = await worker.state(controller)
            await worker.agent(
                {"kind": "navigate", "url": remote_site[0], **epochs(state)}
            )
            held = (
                await host({"kind": "take", **epochs(await worker.state(controller))})
            )["session"]
            assert (
                held["capabilities"]["dragInput"]
                and held["capabilities"]["selectionRead"]
            )
            page = await worker.session._connect_page()
            if display_mode == "x11":
                await host(
                    {"kind": "attach", "viewerId": "window", "surface": "window"}
                )
                await host(
                    {
                        "kind": "frame",
                        "viewerId": "window",
                        "surface": "window",
                        **epochs(held),
                    }
                )
            points = await page.js(RANGE)
            await page.js(
                "window.mousePresses=0;document.addEventListener('mousedown',()=>mousePresses++);true"
            )
            bad = await host(
                {
                    "kind": "input",
                    "surface": "window" if display_mode == "x11" else "page",
                    "input": {
                        "kind": "drag",
                        "points": [{"x": 10, "y": 10}, {"x": -1, "y": 20}],
                    },
                    **epochs(held),
                },
                409,
            )
            assert bad["error"] == "invalid_browser_input"
            assert await page.js("mousePresses") == 0
            await input_event({"kind": "drag", "points": points}, held)
            copied = await host({"kind": "copy-selection", **epochs(held)})
            assert copied["selection"] == {"text": PHRASE, "isAvailable": True}
            # Another authenticated controller cannot read this user's selection.
            denied = await host(
                {"kind": "copy-selection", **epochs(held)}, 409, "user-another"
            )
            assert denied["error"] == "browser_control_not_owned"
            notes = await page.js("""(() => {const r=notes.getBoundingClientRect();
                return {x:r.left+10,y:r.top+10}})()""")
            await input_event({"kind": "click", **notes}, held)
            await page.js(
                "window.pastes=[];notes.addEventListener('input',e=>pastes.push({trusted:e.isTrusted,value:notes.value}));true"
            )
            text = copied["selection"]["text"] + "\n中文 café 😀\tcomment"
            await input_event({"kind": "paste", "text": text}, held)
            assert await page.js("notes.value") == text
            paste_events = await page.js("pastes")
            # Chromium emits several native input events for multiline text.
            # Count the actual review submission, not internal DOM events.
            assert paste_events and all(event["trusted"] for event in paste_events)
            button = await page.js("""(() => {const r=recordNotes.getBoundingClientRect();
                return {x:r.left+10,y:r.top+10}})()""")
            await input_event({"kind": "click", **button}, held)
            receipts = await wait_for(
                lambda: asyncio.sleep(0, result=remote_site[1]), bool
            )
            assert (
                len(receipts) == 1
                and receipts[0]["notes"] == text
                and receipts[0]["trusted"]
            )
            await host({"kind": "return", **epochs(held)})
            stale = await host({"kind": "copy-selection", **epochs(held)}, 409)
            assert stale["error"] == "stale_browser_operation"
            (tmp_path / "selection-evidence.json").write_text(
                json.dumps(
                    {
                        "headless": is_headless,
                        "displayMode": display_mode,
                        "transport": transport,
                        "selected": copied["selection"],
                        "trustedTextExact": True,
                        "serverSubmissionCount": len(receipts),
                        "staleRejected": True,
                        "otherControllerRejected": True,
                        "localOsClipboardRead": False,
                    }
                ),
                encoding="utf-8",
            )
        finally:
            await worker.close()
            await runner.cleanup()


async def test_scaled_surface_drag_selects_exact_phrase(remote_site, tmp_path):
    """Real viewer pointer gesture -> scaled shared surface -> target DOM selection."""
    browsers, connections = [], []
    async with aiohttp.ClientSession() as http:
        try:
            for _ in range(2):
                launched = await asyncio.to_thread(
                    browser_start,
                    headless=True,
                    temp=True,
                    silent_stderr=True,
                    extra_args=["--no-sandbox"] if sys.platform == "linux" else [],
                )
                assert "error" not in launched, launched
                browsers.append(launched)
            await navigate_owned_browser(browsers[0], remote_site[0])
            target, _ = await connect_page(
                http, browsers[0]["port"], browsers[0]["automation_target_id"]
            )
            client, _ = await connect_page(
                http, browsers[1]["port"], browsers[1]["automation_target_id"]
            )
            connections.extend((target, client))
            await target.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": 480, "height": 850, "deviceScaleFactor": 1, "mobile": False},
            )
            remote_site[2](target)
            await navigate_owned_browser(browsers[1], remote_site[0] + "/viewer?drag=1")
            await wait_for(
                lambda: client.js("document.querySelector('#screen')?.naturalWidth"),
                bool,
            )
            points = await target.js(RANGE)
            box = await client.js("""(() => {const r=document.querySelector('#screen').getBoundingClientRect();
                return {x:r.x,y:r.y,width:r.width,height:r.height}})()""")
            points = [
                {
                    "x": box["x"] + p["x"] * box["width"] / 480,
                    "y": box["y"] + p["y"] * box["height"] / 850,
                }
                for p in points
            ]
            await client.call(
                "Input.dispatchMouseEvent", {"type": "mouseMoved", **points[0]}
            )
            await client.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mousePressed",
                    **points[0],
                    "button": "left",
                    "buttons": 1,
                    "clickCount": 1,
                },
            )
            await client.call(
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", **points[1], "buttons": 1},
            )
            await client.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseReleased",
                    **points[1],
                    "button": "left",
                    "buttons": 0,
                    "clickCount": 1,
                },
            )
            selected = await wait_for(
                lambda: PageView().selection(target),
                lambda value: value["text"] == PHRASE,
            )
            (tmp_path / "surface-selection-evidence.json").write_text(
                json.dumps(selected), encoding="utf-8"
            )
        finally:
            await asyncio.gather(*(connection.close() for connection in connections))
            for browser in reversed(browsers):
                await asyncio.to_thread(browser_stop, session_id=browser["session_id"])
