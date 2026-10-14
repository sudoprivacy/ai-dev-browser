"""Native Chrome UI, Unicode input and foreground handoff on owned X11.

The consuming application must separately validate its authenticated UI and
real agent. This fixture owns its display, Chrome and isolated test profile.
"""

import asyncio
import base64
import json
import os
import shutil
import sys
from pathlib import Path

import aiohttp
import pytest

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import (
    connect_browser,
    connect_extension,
    get_active_tab,
)
from ai_dev_browser.core.navigation import page_goto
from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.provision import prepare_managed_extension_profile
from ai_dev_browser.remote.session import BrowserSession
from ai_dev_browser.remote.window import WindowView, XDisplay
from tests.integration.test_remote_view import wait_for

pytest_plugins = ["tests.integration.test_remote_view"]
pytestmark = pytest.mark.skipif(
    sys.platform != "linux"
    or any(
        not shutil.which(tool)
        for tool in ("Xvfb", "openbox", "xprop", "xdotool", "xclip")
    ),
    reason="Isolated X11 display and native input required",
)


@pytest.mark.parametrize("transport", ["cdp", "extension"])
async def test_native_window_tab_and_unicode_handoff(remote_site, transport, tmp_path):
    if transport == "extension" and not os.environ.get(
        "AI_DEV_BROWSER_MANAGED_EXTENSION_PROFILE"
    ):
        pytest.skip("Managed Chrome policy fixture required")
    display = XDisplay()
    previous_display = os.environ.get("DISPLAY")
    launched = client = None
    try:
        os.environ["DISPLAY"] = await display.start()
        view = WindowView(display=os.environ["DISPLAY"])
        options = {"temp": True}
        if transport == "extension":
            profile = os.environ["AI_DEV_BROWSER_MANAGED_EXTENSION_PROFILE"]
            identity = json.loads(
                Path("/opt/browser/extension/identity.json").read_text()
            )
            await prepare_managed_extension_profile(
                profile, extension_id=identity["id"], extra_args=["--no-sandbox"]
            )
            options = {"transport": "extension", "user_data_dir": profile}
        launched = await asyncio.to_thread(
            browser_start,
            headless=False,
            stealth=False,
            silent_stderr=True,
            extra_args=[
                "--no-sandbox",
                "--window-size=1280,900",
                "--start-maximized",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ],
            **options,
        )
        assert "error" not in launched, launched
        client = await (
            connect_extension(session_id=launched["session_id"])
            if transport == "extension"
            else connect_browser(session_id=launched["session_id"])
        )
        await page_goto(await get_active_tab(client), url=remote_site[0])
        async with aiohttp.ClientSession() as http:
            session = BrowserSession(client, http)
            try:
                state = await session.state()
                original = state["activeTargetId"]
                if transport == "extension":
                    browser = await session._connect_browser()
                    scope = await browser.call("AiDevBrowser.debugState")
                    # Chrome can finish initial policy loading after the
                    # extension connects. Wait for the actual positive policy
                    # before exercising native tabs; never infer permission.
                    deadline = asyncio.get_running_loop().time() + 5
                    while (
                        not scope["managedProfile"]
                        and asyncio.get_running_loop().time() < deadline
                    ):
                        await asyncio.sleep(0.1)
                        scope = await browser.call("AiDevBrowser.debugState")
                    assert scope["managedProfile"] is True, scope
                await session.agent_command(0, 0, "Page.bringToFront", {})
                held = await session.take("human", 0, 0)
                frame = await view.capture()
                assert frame["width"] == 1280 and frame["height"] == 900
                (tmp_path / "native-window.jpg").write_bytes(
                    base64.b64decode(frame["data"])
                )

                async def native(event):
                    before = await session.state()

                    async def perform():
                        assert await view.input(event), event

                    await session.control.run(
                        "human", before["controlEpoch"], before["targetEpoch"], perform
                    )
                    await session.follow_foreground(
                        "human", before["controlEpoch"], before["targetEpoch"]
                    )

                # Human input uses native Chrome UI, including a new tab that
                # was not created through automation's Target.createTarget.
                await native({"kind": "key", "key": "NewTab"})

                async def foreground():
                    current = await session.state()
                    await session.follow_foreground(
                        "human", current["controlEpoch"], current["targetEpoch"]
                    )
                    return await session.state()

                switched = await wait_for(
                    foreground, lambda value: value["activeTargetId"] != original
                )
                assert switched["targetEpoch"] > held["targetEpoch"]
                with pytest.raises(ControlError, match="stale"):
                    await session.action(
                        "human",
                        held["controlEpoch"],
                        held["targetEpoch"],
                        {"kind": "reload"},
                    )
                await native({"kind": "key", "key": "AddressBar"})
                await native({"kind": "text", "text": remote_site[0]})
                await native({"kind": "key", "key": "Enter"})

                async def form_ready():
                    state = await session.state()
                    target = next(
                        tab
                        for tab in state["tabs"]
                        if tab["id"] == state["activeTargetId"]
                    )
                    if not target["url"].startswith(remote_site[0]):
                        return False
                    page = await session._connect_page()
                    value = await page.call(
                        "Runtime.evaluate",
                        {
                            "expression": "document.querySelector('#name') !== null",
                            "returnByValue": True,
                        },
                    )
                    return value.get("result", {}).get("value")

                await wait_for(form_ready, bool)
                page = await session._connect_page()
                layout = await page.call(
                    "Runtime.evaluate",
                    {
                        "expression": "(()=>{const r=document.querySelector('#name').getBoundingClientRect();return {x:screenX+r.x+r.width/2,y:screenY+outerHeight-innerHeight+r.y+r.height/2}})()",
                        "returnByValue": True,
                    },
                )
                point = layout["result"]["value"]
                await native({"kind": "click", **point})
                text = "Human review 中文确认"

                async def entered_value():
                    return await page.call(
                        "Runtime.evaluate",
                        {
                            "expression": "({value:document.querySelector('#name').value,focus:document.activeElement.id})",
                            "returnByValue": True,
                        },
                    )

                for expected in [text + str(index) for index in range(8)] + [text]:
                    await native({"kind": "key", "key": "SelectAll"})
                    await native({"kind": "text", "text": expected})
                    entered = await wait_for(
                        entered_value,
                        lambda value, expected=expected: (
                            value.get("result", {}).get("value", {}).get("value")
                            == expected
                        ),
                    )
                (tmp_path / "native-input-diagnostic.json").write_text(
                    json.dumps(
                        {"point": point, "entered": entered["result"].get("value")}
                    )
                )
                (tmp_path / "native-input.jpg").write_bytes(
                    base64.b64decode((await view.capture())["data"])
                )
                current = await session.state()
                with pytest.raises(ControlError, match="held_by_user"):
                    await session.agent_command(
                        current["controlEpoch"],
                        current["targetEpoch"],
                        "Runtime.evaluate",
                        {
                            "expression": "document.querySelector('#name').value='bypass'"
                        },
                    )
                resumed, observed = await session.give_back(
                    "human", current["controlEpoch"], current["targetEpoch"]
                )
                assert observed["activeTargetId"] == switched["activeTargetId"]
                assert any(
                    node.get("value", {}).get("value") == text
                    for node in observed["accessibility"]
                )
                await session.action(
                    "ai",
                    resumed["controlEpoch"],
                    resumed["targetEpoch"],
                    {"kind": "input", "input": {"kind": "click", "x": 80, "y": 110}},
                )
                await wait_for(lambda: asyncio.sleep(0, result=remote_site[1]), bool)
                assert len(remote_site[1]) == 1
                assert remote_site[1][0]["name"] == text
                assert remote_site[1][0]["trusted"] is True
                assert remote_site[1][0]["cookie"] == "isolated"
                (tmp_path / "native-handoff-evidence.json").write_text(
                    json.dumps(
                        {
                            "transport": transport,
                            "nativeTabFollowed": True,
                            "unicodeInput": True,
                            "receipt": remote_site[1][0],
                        },
                        indent=2,
                    )
                )
            finally:
                await session.close()
    finally:
        await view.close()
        if client:
            await client.close()
        if launched and "error" not in launched:
            stopped = await asyncio.to_thread(
                browser_stop, session_id=launched["session_id"]
            )
            assert stopped.get("stopped"), stopped
        await display.close()
        if previous_display is None:
            os.environ.pop("DISPLAY", None)
        else:
            os.environ["DISPLAY"] = previous_display
