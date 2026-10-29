"""Real extension child frames stay attached to their owning browser tab."""

import asyncio
import json
import os
from pathlib import Path

from aiohttp import web
import pytest

from ai_dev_browser.cdp import dom, input_, page, target
from ai_dev_browser.core.connection import (
    BrowserClient,
    connect_extension,
    get_active_tab,
)
from ai_dev_browser.core import js_evaluate
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.remote.provision import prepare_managed_extension_profile


async def wait_value(read, expected):
    deadline = asyncio.get_running_loop().time() + 10
    while True:
        value = await read()
        if value == expected:
            return value
        assert asyncio.get_running_loop().time() < deadline, (value, expected)
        await asyncio.sleep(0.05)


@pytest.fixture
async def frame_site():
    port = None

    async def parent(request):
        owner = request.match_info["owner"]
        assert owner in ("first", "second")
        return web.Response(
            content_type="text/html",
            text=f'''<!doctype html>
<h1>Parent {owner}</h1><iframe id="review" name="{owner}" src="http://child.test:{port}/child"></iframe>''',
        )

    async def child(_request):
        return web.Response(
            content_type="text/html",
            text=f"""<!doctype html><meta charset="utf-8">
<h1 id="heading"></h1><input id="value"><script>
heading.textContent='Child '+window.name;window.trust=[];value.oninput=e=>trust.push(e.isTrusted);
const nested=document.createElement('iframe');nested.name='nested-'+window.name;
nested.src='http://grandchild.test:{port}/grandchild';document.body.append(nested);
</script>""",
        )

    async def grandchild(_request):
        return web.Response(
            content_type="text/html",
            text="""<!doctype html><h1 id="nested"></h1>
<script>nested.textContent=window.name</script>""",
        )

    app = web.Application()
    app.add_routes(
        [
            web.get("/parent/{owner}", parent),
            web.get("/child", child),
            web.get("/grandchild", grandchild),
        ]
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield port
    finally:
        await runner.cleanup()


async def owned_frame_id(tab):
    document = await tab.send(dom.get_document(depth=1))
    node = await tab.send(dom.query_selector(document.node_id, "#review"))
    owned = await tab.send(dom.describe_node(node_id=node))
    assert owned.frame_id
    return str(owned.frame_id)


async def verify_owned_frames(browser, port, proof):
    """Run the same frame/input/lifecycle contract on either real transport."""
    first = await get_active_tab(browser)
    # Register the other tab's identical child URL first. Global URL matching
    # would silently read or type into the wrong task.
    other_id = await browser.connection.send(
        target.create_target(f"http://parent.test:{port}/parent/second")
    )
    await browser.update_targets()
    second = next(t for t in browser.tabs if t._target.target_id == other_id)
    await wait_value(
        lambda: second.evaluate(
            "!!document.querySelector('#review')", return_by_value=True
        ),
        True,
    )
    foreign_id = await owned_frame_id(second)
    # Attaching proves the foreign frame has actually registered before the
    # selected tab refuses it, rather than passing on a startup race.
    await second.frame_session(foreign_id)
    await first.send(page.navigate(f"http://parent.test:{port}/parent/first"))
    await wait_value(
        lambda: first.evaluate(
            "!!document.querySelector('#review')", return_by_value=True
        ),
        True,
    )
    with pytest.raises(ValueError):
        await first.frame_session(foreign_id)
    frame_id = await owned_frame_id(first)
    session = await first.frame_session(frame_id)

    async def child_value(expression):
        result = await js_evaluate(first, expression, frame="//child.test:")
        return result["result"]

    assert (await js_evaluate(first, "heading.textContent", frame=frame_id))[
        "result"
    ] == "Child first"
    assert await child_value("heading.textContent") == "Child first"
    assert (await js_evaluate(first, "nested.textContent", frame="grandchild.test"))[
        "result"
    ] == "nested-first"
    # Both URLs contain child.test; selecting a broad substring must fail.
    with pytest.raises(ValueError, match="Ambiguous iframe"):
        await first.frame_session("child.test")
    await child_value("document.querySelector('#value').focus()")
    text = "Frame \u4e2d\u6587"
    await first.send(input_.insert_text(text), session_id=session)
    assert await child_value("document.querySelector('#value').value") == text
    assert await child_value("trust") == [True]
    assert (
        await js_evaluate(
            second, "document.querySelector('#value').value", frame="//child.test:"
        )
    )["result"] == ""
    assert (
        await first.evaluate("!!document.querySelector('#value')", return_by_value=True)
        is False
    )
    proof.update(
        ownedFrameId=frame_id,
        otherTabFrameRefused=True,
        nestedFrameOwned=True,
        ambiguousUrlRefused=True,
        trustedChineseInput=True,
        otherTabUnchanged=True,
    )

    next_url = f"http://child.test:{port}/child?document=next"
    await first.evaluate(
        "(()=>{const frame=document.querySelector('#review');window.childLoaded=false;"
        "frame.addEventListener('load',()=>{window.childLoaded=true},{once:true});"
        f"frame.src={json.dumps(next_url)};return true}})()"
    )
    await wait_value(
        lambda: first.evaluate("window.childLoaded", return_by_value=True), True
    )
    assert await owned_frame_id(first) == frame_id
    assert (await js_evaluate(first, "location.search", frame=frame_id))[
        "result"
    ] == "?document=next"
    assert (await js_evaluate(first, "heading.textContent", frame=next_url))[
        "result"
    ] == "Child first"
    proof["sameFrameNavigationMetadataRefreshed"] = True
    session = await first.frame_session(frame_id)

    await first.evaluate("document.querySelector('#review').remove()")

    async def detached():
        return session not in first._frame_sessions.values()

    await wait_value(detached, True)
    await first.send(page.navigate(f"http://parent.test:{port}/parent/first?reload=1"))
    await wait_value(
        lambda: first.evaluate(
            "!!document.querySelector('#review')", return_by_value=True
        ),
        True,
    )
    assert await child_value("heading.textContent") == "Child first"
    assert await child_value("document.querySelector('#value').value") == ""
    proof.update(detachedSessionEvicted=True, recreatedFrameRead=True)


@pytest.mark.extension_frames
async def test_real_extension_owned_child_frame_lifecycle(
    live_extension, frame_site, tmp_path
):
    proof = {
        "passed": False,
        "actualExtension": True,
        "backendPort": live_extension.port,
    }
    browser = None
    try:
        browser = await BrowserClient.connect(
            "127.0.0.1",
            live_extension.port,
            ws_url=f"ws://127.0.0.1:{live_extension.port}/devtools/browser",
        )
        browser.transport = "extension"
        await verify_owned_frames(browser, frame_site, proof)

        # A fresh SDK client uses the same browser/profile and must rediscover
        # only the selected tab's child sessions, without navigating either tab.
        await browser.close()
        browser = None
        assert (
            await live_extension.call(
                js_evaluate,
                tab_url="/parent/first",
                expression="heading.textContent",
                frame="//child.test:",
            )
        )["result"] == "Child first"
        proof.update(passed=True, freshClientSameFrame=True)
    finally:
        if browser is not None:
            await browser.close()
        (tmp_path / "child-frame-receipt.json").write_text(
            json.dumps(proof, indent=2), encoding="utf8"
        )


async def test_native_frame_session_refuses_another_tabs_child(frame_site, tmp_path):
    proof = {"passed": False, "transport": "cdp"}
    chrome = await asyncio.to_thread(
        browser_start,
        headless=True,
        temp=True,
        reuse="none",
        silent_stderr=True,
        extra_args=[
            "--host-resolver-rules=MAP *.test 127.0.0.1",
            "--proxy-server=direct://",
            "--no-sandbox",
        ],
    )
    assert "error" not in chrome, chrome
    browser = None
    try:
        browser = await BrowserClient.connect("127.0.0.1", chrome["port"])
        await verify_owned_frames(browser, frame_site, proof)
        proof["passed"] = True
    finally:
        if browser is not None:
            await browser.close()
        proof["ownedBrowserStopped"] = await asyncio.to_thread(
            browser_stop, session_id=chrome["session_id"]
        )
        (tmp_path / "native-frame-receipt.json").write_text(
            json.dumps(proof, indent=2), encoding="utf8"
        )


@pytest.mark.skipif(
    not os.environ.get("AI_DEV_BROWSER_MANAGED_EXTENSION_PROFILE"),
    reason="Signed managed Chrome fixture required",
)
async def test_managed_extension_owned_child_frame_lifecycle(frame_site, tmp_path):
    proof = {"passed": False, "transport": "extension", "signedManagedChrome": True}
    profile = os.environ["AI_DEV_BROWSER_MANAGED_EXTENSION_PROFILE"]
    identity = json.loads(Path("/opt/browser/extension/identity.json").read_text())
    args = [
        "--host-resolver-rules=MAP *.test 127.0.0.1",
        "--proxy-server=direct://",
        "--no-sandbox",
    ]
    await prepare_managed_extension_profile(
        profile, extension_id=identity["id"], extra_args=args
    )
    chrome = await asyncio.to_thread(
        browser_start,
        headless=True,
        stealth=False,
        transport="extension",
        user_data_dir=profile,
        silent_stderr=True,
        extra_args=args,
    )
    assert "error" not in chrome, chrome
    browser = None
    try:
        browser = await connect_extension(session_id=chrome["session_id"])
        await verify_owned_frames(browser, frame_site, proof)
        await browser.close()
        browser = await connect_extension(session_id=chrome["session_id"])
        first = await get_active_tab(browser)
        result = await js_evaluate(first, "heading.textContent", frame="//child.test:")
        assert result["result"] == "Child first"
        proof.update(
            passed=True, freshClientSameFrame=True, extensionVersion=identity["version"]
        )
    finally:
        if browser is not None:
            await browser.close()
        proof["ownedBrowserStopped"] = await asyncio.to_thread(
            browser_stop, session_id=chrome["session_id"]
        )
        assert proof["ownedBrowserStopped"]["stopped"], proof
        (tmp_path / "managed-child-frame-receipt.json").write_text(
            json.dumps(proof, indent=2), encoding="utf8"
        )
