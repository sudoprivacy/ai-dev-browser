"""Reproduce a real Chrome navigation cancellation with a second owned driver."""

import asyncio
import sys
import json
import threading

import aiohttp
import pytest
from aiohttp import web

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core import browser as lifecycle
from ai_dev_browser.core import (
    click_by_html_id,
    browser_reconnect,
    page_goto,
    page_screenshot,
    type_by_text,
)
from ai_dev_browser.core.connection import connect_browser, get_active_tab
from ai_dev_browser.core.process import _kill_process_tree
from ai_dev_browser.remote.cdp import CDP
from tests.integration.test_remote_view import (
    connect_page,
    navigate_owned_browser,
    wait_for,
)


async def startup_target_journey(
    folder, monkeypatch, headless, with_url=False, slow_initial=False
):
    """Let an independent startup actor navigate its early page during first use."""
    loop = asyncio.get_running_loop()
    announced = loop.create_future()
    release_launch = threading.Event()
    first_request = asyncio.Event()
    release_request = asyncio.Event()
    requests, receipts = [], []
    browser = process = actor = root = controller = navigation = launch_task = None
    early_id = None
    real_launch = lifecycle.launch_chrome

    async def page(request):
        requests.append(request.path)
        first_request.set()
        await release_request.wait()
        return web.Response(
            text="""<!doctype html><meta charset="utf-8">
            <h1>Owned startup page</h1>
            <label>Request name<input name="name" id="name"></label>
            <button id="submit">Submit once</button><pre id="receipt"></pre>
            <script>window.inputTrust=[];document.querySelector('#name').oninput=e=>inputTrust.push(e.isTrusted);
            submit.onclick=async e=>{const r=await fetch('/receipt',{method:'POST',
            headers:{'Content-Type':'application/json'},body:JSON.stringify({
            name:document.querySelector('#name').value,trusted:e.isTrusted})});
            receipt.textContent=JSON.stringify(await r.json())};</script>""",
            content_type="text/html",
        )

    async def receipt(request):
        value = await request.json()
        receipts.append(value)
        return web.json_response(value)

    app = web.Application()
    app.router.add_get("/first", page)
    app.router.add_post("/receipt", receipt)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/first"

    def launch(**options):
        owned = real_launch(**options)
        loop.call_soon_threadsafe(announced.set_result, (owned, options["port"]))
        if not release_launch.wait(10):
            raise TimeoutError("Startup actor was not prepared")
        return owned

    monkeypatch.setattr(lifecycle, "launch_chrome", launch)
    try:
        launch_task = asyncio.create_task(
            asyncio.to_thread(
                browser_start,
                temp=True,
                headless=headless,
                stealth=False,
                silent_stderr=True,
                url=url if with_url else None,
                startup_timeout=3 if slow_initial else None,
                extra_args=["--no-sandbox"] if sys.platform == "linux" else [],
            )
        )
        process, port = await asyncio.wait_for(announced, 10)
        async with aiohttp.ClientSession() as http:

            async def identity():
                try:
                    async with http.get(
                        f"http://127.0.0.1:{port}/json/version"
                    ) as reply:
                        return await reply.json()
                except aiohttp.ClientError:
                    return None

            version = await wait_for(identity, bool, timeout=10)
            root = CDP(await http.ws_connect(version["webSocketDebuggerUrl"]))
            pages = (await root.call("Target.getTargets"))["targetInfos"]
            pages = [item for item in pages if item["type"] == "page"]
            # Arrange a real early Chrome page before high-level startup resumes.
            # This actor owns that page and can finish its own startup later.
            early_id = (
                pages[0]["targetId"]
                if pages
                else (await root.call("Target.createTarget", {"url": "about:blank"}))[
                    "targetId"
                ]
            )
            actor = CDP(
                await http.ws_connect(f"ws://127.0.0.1:{port}/devtools/page/{early_id}")
            )
            await actor.call("Page.enable")
            release_launch.set()
            if with_url:
                await asyncio.wait_for(first_request.wait(), 10)
                await actor.call("Page.navigate", {"url": "about:blank"})
                if not slow_initial:
                    release_request.set()
            browser = await asyncio.wait_for(launch_task, 15)
            initial_timeout = None
            if slow_initial:
                initial_timeout = browser
                assert browser.get("error_code") == "transient", browser
                assert browser["connected"] is False and not browser["browser_closed"]
                assert browser["automation_target_id"] != early_id
                assert process.poll() is None and requests == ["/first"]
                release_request.set()
                browser = await browser_reconnect(browser["session_id"])
                assert browser["session_id"] == initial_timeout["session_id"]
                assert (
                    browser["automation_target_id"]
                    == initial_timeout["automation_target_id"]
                )
            assert "error" not in browser, browser
            assert browser["pid"] == process.pid
            controller = await connect_browser(
                port=port, session_id=browser["session_id"]
            )
            owned = await get_active_tab(controller)
            if not with_url:
                navigation = asyncio.create_task(page_goto(owned, url))
            await asyncio.wait_for(first_request.wait(), 10)
            await actor.call("Page.navigate", {"url": "about:blank"})
            release_request.set()
            if navigation:
                result = await asyncio.wait_for(navigation, 15)
                assert result["ready"] and result["url"] == url, result
            observed = await wait_for(
                lambda: owned.evaluate(
                    "({url:location.href,ready:document.readyState,heading:document.querySelector('h1')?.textContent})",
                    return_by_value=True,
                ),
                lambda value: value["url"] == url
                and value["ready"] == "complete"
                and value["heading"] == "Owned startup page",
                timeout=10,
            )
            assert requests == ["/first"]
            assert await actor.js("location.href") == "about:blank"
            typed = await type_by_text(
                owned, name="Request name", text="Startup accepted"
            )
            assert typed["verified"] and typed["method"] != "native"
            trust = await owned.evaluate("window.inputTrust", return_by_value=True)
            assert trust and all(trust)
            assert (await click_by_html_id(owned, html_id="submit"))["clicked"]
            await wait_for(
                lambda: owned.evaluate(
                    "document.querySelector('#receipt').textContent"
                ),
                bool,
            )
            assert receipts == [{"name": "Startup accepted", "trusted": True}]
            await page_screenshot(
                owned, path=str(folder / "startup-target-accepted.png")
            )
            (folder / "startup-target-evidence.json").write_text(
                json.dumps(
                    {
                        "browser": version["Browser"],
                        "headless": headless,
                        "with_startup_url": with_url,
                        "initial_document_timeout": initial_timeout,
                        "same_process": browser["pid"] == process.pid,
                        "early_target": early_id,
                        "owned_target": browser["automation_target_id"],
                        "early_target_url": await actor.js("location.href"),
                        "observed": observed,
                        "requests": requests,
                        "trusted_input": trust,
                        "receipts": receipts,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
    finally:
        release_launch.set()
        release_request.set()
        if navigation and not navigation.done():
            navigation.cancel()
            await asyncio.gather(navigation, return_exceptions=True)
        for peer in (controller, actor, root):
            if peer:
                await peer.close()
        if launch_task and not launch_task.done():
            outcome = await asyncio.gather(launch_task, return_exceptions=True)
            if isinstance(outcome[0], dict):
                browser = outcome[0]
        if browser and "session_id" in browser:
            stopped = await asyncio.to_thread(
                browser_stop, session_id=browser["session_id"]
            )
            assert stopped["stopped"], stopped
        elif process and process.poll() is None:
            await asyncio.to_thread(_kill_process_tree, process.pid)
        await runner.cleanup()


async def startup_race_journey(folder, accepted=True):
    first_request = asyncio.Event()
    release_first = asyncio.Event()
    requests = []
    bootstrap_requests = []
    phases = []

    async def page(request):
        requests.append(request.path)
        phases.append({"phase": "target-request", "count": len(requests)})
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

    async def bootstrap(request):
        bootstrap_requests.append(request.path)
        return web.Response(
            text='<title>Race fixture ready</title><main id="bootstrap">Ready</main>',
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    app.router.add_get("/bootstrap", bootstrap)

    async def redirect(request):
        phases.append({"phase": "competing-redirect"})
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
    bootstrap_url = url.replace("/target", "/bootstrap")
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
                # Establish the actors' neutral document before their deliberate
                # competing navigations. Setup dispatches exactly once.
                prepared = await peer.call("Page.navigate", {"url": bootstrap_url})
                assert "errorText" not in prepared, prepared
                await peer.wait_navigation(prepared, timeout=10)
                ready = await wait_for(
                    lambda: peer.js(
                        "({url:location.href,ready:document.readyState,"
                        "marker:document.querySelector('#bootstrap')?.textContent})"
                    ),
                    lambda value: value["url"] == bootstrap_url
                    and value["ready"] in ("interactive", "complete")
                    and value["marker"] == "Ready",
                    timeout=10,
                )
                assert bootstrap_requests == ["/bootstrap"] and requests == []
                phases.append({"phase": "bootstrap-ready", "observed": ready})
                navigation = asyncio.create_task(
                    navigate_owned_browser(
                        browser, url, folder, settle_timeout=15 if accepted else 2
                    )
                )
                await asyncio.wait_for(first_request.wait(), 10)
                phases.append({"phase": "first-target-held"})
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
        (folder / "startup-navigation-race-evidence.json").write_text(
            json.dumps(
                {
                    "bootstrapRequests": bootstrap_requests,
                    "targetRequests": requests,
                    "phases": phases,
                    "acceptedDestination": accepted,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if browser and "session_id" in browser:
            stopped = await asyncio.to_thread(
                browser_stop, session_id=browser["session_id"]
            )
            assert stopped["stopped"]
        await runner.cleanup()
