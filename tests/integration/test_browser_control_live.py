"""AI/human lease semantics against one actual Chrome page and profile.

This tests the browser operation boundary, not an LLM/host execution barrier.
Consumers must additionally exercise their actual agent runtime and UI.
"""

import asyncio
import base64
import sys
from io import BytesIO

import aiohttp
import pytest
from PIL import Image

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.remote.control import BrowserControl, ControlError
from ai_dev_browser.remote.page import PageView
from tests.integration.test_remote_view import (
    connect_page,
    navigate_owned_browser,
    wait_for,
)

pytest_plugins = ["tests.integration.test_remote_view"]


async def test_human_login_then_ai_continues_on_same_page(remote_site, tmp_path):
    browser = await asyncio.to_thread(
        browser_start,
        headless=True,
        stealth=False,
        temp=True,
        silent_stderr=True,
        extra_args=["--no-sandbox"] if sys.platform == "linux" else [],
    )
    assert "error" not in browser, browser
    control, view = BrowserControl(), PageView()
    try:
        await navigate_owned_browser(browser, remote_site[0])
        async with aiohttp.ClientSession() as http:
            page, target = await connect_page(http, browser["port"])
            try:
                assert target == browser["automation_target_id"]

                async def text(value):
                    await view.input(
                        page, {"kind": "click", "x": 80, "y": 45}, width=480, height=850
                    )
                    await view.input(
                        page, {"kind": "text", "text": value}, width=480, height=850
                    )

                state = await control.take("test-user")
                await control.run(
                    "test-user", state["controlEpoch"], 0, lambda: text("人工登录完成")
                )
                # A delayed AI or child action must not overwrite human input.
                with pytest.raises(ControlError, match="stale_browser_operation"):
                    await control.run("ai", 0, 0, lambda: text("stale"))
                with pytest.raises(ControlError, match="browser_control_held_by_user"):
                    await control.run(
                        "ai", state["controlEpoch"], 0, lambda: text("bypass")
                    )

                async def observe():
                    return {
                        "name": await page.js("document.querySelector('#name').value"),
                        "url": await page.js("location.href"),
                        "cookie": await page.js("document.cookie"),
                        "image": await view.capture(page),
                        "target": target,
                    }

                resumed, fresh = await control.give_back("test-user", observe)
                assert fresh["name"] == "人工登录完成"
                assert fresh["url"].rstrip("/") == remote_site[0]
                assert "profile=isolated" in fresh["cookie"]
                assert fresh["target"] == browser["automation_target_id"]
                image = Image.open(BytesIO(base64.b64decode(fresh["image"]))).convert(
                    "RGB"
                )
                assert (
                    image.width > 100
                    and len(image.getcolors(image.width * image.height) or []) > 10
                )
                image.save(tmp_path / "human-state-before-ai.png")
                await control.run(
                    "ai",
                    resumed["controlEpoch"],
                    0,
                    lambda: view.input(
                        page,
                        {"kind": "click", "x": 80, "y": 110},
                        width=480,
                        height=850,
                    ),
                )
                await wait_for(
                    lambda: page.js("document.querySelector('#receipt').textContent"),
                    bool,
                )
                assert remote_site[1] == [
                    {
                        "name": "人工登录完成",
                        "trusted": True,
                        "press": {"buttons": 1, "trusted": True},
                        "cookie": "isolated",
                        "sequence": 1,
                    }
                ]
                # Losing a viewer after a second takeover must leave AI paused.
                await control.take("test-user")
                await page.close()
                assert control.state == "human"
            finally:
                await page.close()
    finally:
        stopped = await asyncio.to_thread(
            browser_stop, session_id=browser["session_id"]
        )
        assert stopped["stopped"], stopped
