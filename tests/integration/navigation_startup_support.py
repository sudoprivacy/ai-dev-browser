"""Reproduce a real Chrome navigation cancellation with a second owned driver."""

import asyncio
import sys
import json

import aiohttp
import pytest
from aiohttp import web

from ai_dev_browser.core.browser import browser_start, browser_stop
from tests.integration.test_remote_view import connect_page, navigate_owned_browser


async def startup_race_journey(folder, accepted=True):
    first_request = asyncio.Event()
    release_first = asyncio.Event()
    requests = []

    async def page(request):
        requests.append(request.path)
        if len(requests) == 1:
            first_request.set()
            await release_first.wait()
        return web.Response(
            text="<title>Ready once</title><h1 id=ready>Correct destination</h1>",
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    app = web.Application()
    app.router.add_get("/target", page)

    async def redirect(request):
        raise web.HTTPFound("/target" if accepted else "/wrong")

    app.router.add_get("/redirect", redirect)

    async def wrong(request):
        return web.Response(
            text="<h1 id=ready>Wrong destination</h1>", content_type="text/html"
        )

    app.router.add_get("/wrong", wrong)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/target"
    browser = None
    navigation = None
    try:
        browser = await asyncio.to_thread(
            browser_start,
            headless=True,
            temp=True,
            stealth=False,
            silent_stderr=True,
            extra_args=["--no-sandbox"] if sys.platform == "linux" else [],
        )
        assert "error" not in browser, browser
        async with aiohttp.ClientSession() as http:
            peer, _ = await connect_page(
                http, browser["port"], browser["automation_target_id"]
            )
            try:
                navigation = asyncio.create_task(
                    navigate_owned_browser(
                        browser, url, folder, settle_timeout=15 if accepted else 2
                    )
                )
                await asyncio.wait_for(first_request.wait(), 10)
                # This independent owned driver is the controlled competing
                # browser navigation; the helper itself still dispatches once.
                await asyncio.wait_for(
                    peer.call(
                        "Page.navigate", {"url": url.replace("/target", "/redirect")}
                    ),
                    timeout=10,
                )
                if not accepted:
                    with pytest.raises(
                        AssertionError, match="Browser state did not arrive"
                    ):
                        await asyncio.wait_for(navigation, 20)
                    evidence = json.loads(
                        (folder / "startup-navigation-evidence.json").read_text()
                    )
                    assert (
                        "ERR_ABORTED" in evidence["error"]
                        and evidence["result"] is None
                    )
                    assert evidence["observed"]["url"].endswith("/wrong")
                    assert requests == ["/target"]
                    return
                result = await asyncio.wait_for(navigation, 20)
                assert result["startup_navigation_aborted"] is True, result
                assert (
                    await peer.js("document.querySelector('#ready').textContent")
                    == "Correct destination"
                )
                assert requests == ["/target", "/target"], requests
            finally:
                release_first.set()
                if navigation and not navigation.done():
                    navigation.cancel()
                    await asyncio.gather(navigation, return_exceptions=True)
                await peer.close()
    finally:
        release_first.set()
        if browser and "session_id" in browser:
            stopped = await asyncio.to_thread(
                browser_stop, session_id=browser["session_id"]
            )
            assert stopped["stopped"]
        await runner.cleanup()
