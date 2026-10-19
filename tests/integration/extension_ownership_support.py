"""Neutral real-browser workflows for navigation ownership and input receipts."""

import asyncio
import json
from pathlib import Path
import os
import shutil
import sys

from aiohttp import web

from ai_dev_browser.core import click_by_html_id, get_active_tab
from ai_dev_browser.core.connection import BrowserClient
from ai_dev_browser.core.cdp import cdp_send, _get_cdp_command
from ai_dev_browser.cdp import runtime
from ai_dev_browser.core import connect_browser
from ai_dev_browser.core._transport import OwnershipProtocolError
from ai_dev_browser._cli import _exception_failure, _exit_code_for_result
import pytest


async def worker_call(extension, expression):
    """Fault setup/inspection through only this fixture's real extension worker."""
    control = await connect_browser(port=extension.chrome_port)
    try:
        for target in control.targets:
            if target.type_ != "service_worker":
                continue
            try:
                identity, error = await target._connection.send(
                    runtime.evaluate(
                        "typeof BRIDGE === 'string' ? BRIDGE : null",
                        return_by_value=True,
                    )
                )
                if (
                    error is None
                    and identity.value == f"ws://127.0.0.1:{extension.port}"
                ):
                    value, error = await target._connection.send(
                        runtime.evaluate(
                            expression, return_by_value=True, await_promise=True
                        )
                    )
                    assert error is None, error
                    return value.value
            finally:
                await target._connection.disconnect()
        raise AssertionError("Owned fixture worker not found")
    finally:
        await control.close()


async def connect(extension):
    browser = await BrowserClient.connect(
        "127.0.0.1",
        extension.port,
        ws_url=f"ws://127.0.0.1:{extension.port}/devtools/browser",
    )
    browser.transport = "extension"
    return browser


async def wait_until(operation, predicate, timeout=10):
    async with asyncio.timeout(timeout):
        while True:
            result = await operation()
            if predicate(result):
                return result
            await asyncio.sleep(0.05)


async def cli(extension, folder, *arguments, code=0):
    env = {k: v for k, v in os.environ.items() if not k.startswith("AI_DEV_BROWSER_")}
    env["AI_DEV_BROWSER_EXTENSION_BRIDGE_PORT"] = str(extension.port)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "ai_dev_browser.tools.js_evaluate",
        "--transport",
        "extension",
        "--expression",
        "document.title",
        *arguments,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(process.communicate(), timeout=30)
    assert process.returncode == code, (out, err)
    payload = json.loads(out)
    (folder / f"cli-{code}-evidence.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return payload


async def navigation_journey(extension, folder: Path, mode: str):
    receipts = []
    url = ""

    async def receipt(request):
        receipts.append(await request.json())
        return web.json_response({"accepted": True})

    async def page(request):
        destination = url.replace("127.0.0.1", "localhost") if mode != "same" else url
        landing = destination + "/result?private=must-not-log#private-fragment"
        action = f"location.href={json.dumps(landing)}"
        if mode in ("child", "noopener", "close-parent"):
            feature = ", 'noopener'" if mode == "noopener" else ""
            action = f"window.open({json.dumps(landing)}, '_blank'{feature});"
            if mode == "close-parent":
                action += "window.close();"
        if request.path == "/result":
            return web.Response(
                text="<title>Confirmed result</title><h1 id=done>One submission</h1>",
                content_type="text/html",
            )
        html = f"""<!doctype html><title>Ownership consent</title>
<style>button{{font:24px sans-serif;padding:30px;margin:50px}}</style>
<button id=submit>Confirm once</button><script>
document.querySelector('#submit').onclick=async e=>{{
await fetch('/receipt',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{trusted:e.isTrusted,mode:{json.dumps(mode)}}})}});
{action}
}};</script>"""
        return web.Response(text=html, content_type="text/html")

    app = web.Application()
    app.router.add_post("/receipt", receipt)
    app.router.add_get("/{tail:.*}", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    browser = None
    try:
        browser = await connect(extension)
        parent = await browser.get(url)
        parent_id = str(parent.target_id)
        sentinel = await worker_call(
            extension,
            f"chrome.tabs.create({{url:{json.dumps(url + '/unrelated?secret=unrelated-private')},active:false}}).then(t=>t.id)",
        )
        await browser.close()
        browser = await connect(extension)
        parent = await get_active_tab(browser, url_contains=url)
        assert str(parent.target_id) == parent_id
        await parent.activate()
        clicked = await click_by_html_id(parent, html_id="submit")
        assert clicked["clicked"], clicked
        await wait_until(lambda: asyncio.sleep(0, result=receipts), bool)

        async def targets():
            await browser.update_targets()
            return [{"id": str(tab.target_id), "url": tab.url} for tab in browser.tabs]

        listed = await wait_until(
            targets, lambda values: any("/result" in value["url"] for value in values)
        )
        result = await get_active_tab(browser, url_contains="/result")
        assert str(sentinel) not in {item["id"] for item in listed}
        with pytest.raises(OwnershipProtocolError) as unowned:
            await browser.connection.send(
                _get_cdp_command("Target.getTargetInfo", {"targetId": str(sentinel)})
            )
        assert unowned.value.details["state"] == "unowned"
        with pytest.raises(OwnershipProtocolError):
            await browser.connection.send(
                _get_cdp_command("Target.activateTarget", {"targetId": str(sentinel)})
            )
        if mode == "close-parent":
            with pytest.raises(OwnershipProtocolError) as closed:
                await parent.evaluate("document.title")
            assert closed.value.error_code == "target_closed"
        observed = await result.evaluate("document.querySelector('#done').textContent")
        assert observed == "One submission"
        if mode in ("same", "cross"):
            assert str(result.target_id) == parent_id
            assert await parent.evaluate("document.title") == "Confirmed result"
        else:
            assert str(result.target_id) != parent_id
        await browser.close()
        await extension.restart_worker()
        browser = await connect(extension)
        restored = await get_active_tab(browser, url_contains="/result")
        assert str(restored.target_id) == str(result.target_id)
        assert await restored.evaluate("document.title") == "Confirmed result"
        success = await cli(extension, folder, "--tab-url", "/result")
        assert success["result"] == "Confirmed result"
        missing = await cli(
            extension, folder, "--tab-url", "/missing?private=must-not-log", code=4
        )
        assert missing["error_code"] == "not_found" and missing["retryable"] is False
        assert "must-not-log" not in json.dumps(missing)
        assert "unrelated-private" not in json.dumps(missing)
        assert receipts == [{"trusted": True, "mode": mode}], receipts
        diagnostics = await cdp_send(restored, method="AiDevBrowser.debugState")
        assert "must-not-log" not in json.dumps(
            diagnostics
        ) and "private-fragment" not in json.dumps(diagnostics)
        evidence = {
            "mode": mode,
            "parent": parent_id,
            "result": str(result.target_id),
            "targets": [
                {"id": item["id"], "path": item["url"].split("?", 1)[0]}
                for item in listed
            ],
            "receipts": receipts,
            "debug": diagnostics["result"],
        }
        (folder / "ownership-evidence.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
    finally:
        if browser:
            await browser.close()
        await runner.cleanup()


async def cancellation_journey(extension, folder):
    """Click Chrome's real Cancel banner in an isolated X11 display."""
    from PIL import ImageGrab, ImageFilter

    assert os.environ.get("DISPLAY") and shutil.which("xdotool")
    browser = await connect(extension)
    try:
        tab = await browser.get(
            "data:text/html,<title>Owned revocation fixture</title><h1>Cancel permission</h1>"
        )
        tid = str(tab.target_id)
        await tab.activate()

        async def native(*args):
            process = await asyncio.create_subprocess_exec(
                "xdotool",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await process.communicate()
            assert process.returncode == 0, (args, out, err)
            return out.decode().strip()

        window = (
            await native(
                "search",
                "--onlyvisible",
                "--pid",
                str(extension.chrome_pid),
                "--name",
                "Owned revocation fixture",
            )
        ).splitlines()[0]
        await native("windowactivate", "--sync", window)

        # Locate the solid blue native Cancel button; DOM input cannot click
        # Chrome's permission UI. Work only inside this fixture's X11 display.
        def blue(pixel):
            r, g, b = pixel[:3]
            return r < 50 and 50 < g < 150 and b > 160

        async def banner():
            shot = ImageGrab.grab()
            region = shot.convert("RGB").crop((0, 90, shot.width, 260))
            mask = region.convert("L")
            mask.putdata([255 if blue(p) else 0 for p in region.getdata()])
            return shot, mask.filter(ImageFilter.MinFilter(9)).getbbox()

        try:
            image, bounds = await wait_until(
                banner,
                lambda pair: pair[1]
                and 30 < pair[1][2] - pair[1][0] < 150
                and 10 < pair[1][3] - pair[1][1] < 50,
            )
        except TimeoutError:
            ImageGrab.grab().save(folder / "cancel-not-visible.png")
            raise
        image.save(folder / "cancel-before.png")
        x, y = (bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2 + 90
        await native("mousemove", "--sync", str(x), str(y), "click", "1")

        async def state():
            return await browser.connection.send(
                _get_cdp_command("AiDevBrowser.debugState", {})
            )

        cancelled = await wait_until(
            state,
            lambda current: any(
                t["target_id"] == tid and t["state"] == "revoked"
                for t in current["targetStates"]
            ),
        )

        # Wait through Chrome's closing animation before retaining the screenshot.
        after_image, _ = await wait_until(banner, lambda pair: pair[1] is None)
        after_image.save(folder / "cancel-after.png")
        with pytest.raises(OwnershipProtocolError) as refusal:
            await tab.evaluate("document.title")
        with pytest.raises(OwnershipProtocolError):
            await click_by_html_id(tab, html_id="never-submit")
        envelope = _exception_failure(refusal.value, None)
        assert (
            envelope["details"]["state"] == "revoked" and envelope["retryable"] is False
        )
        assert (
            envelope["error_code"] == "auth_failed"
            and _exit_code_for_result(envelope) == 7
        )
        assert any(
            e["event"] == "detached" and e["reason"] == "canceled_by_user"
            for e in cancelled["ownershipLog"]
        )
        await browser.close()
        browser = await connect(extension)
        assert not browser.tabs
        refused = await cli(extension, folder, code=7)
        assert (
            refused["error_code"] == "auth_failed"
            and refused["details"]["state"] == "revoked"
        )
        assert not browser.tabs
        await browser.close()
        await extension.restart_worker()
        browser = await connect(extension)
        after = await state()
        assert int(tid) not in after["autoTabs"] and int(tid) not in after["attached"]
        assert not browser.tabs
        (folder / "cancel-evidence.json").write_text(
            json.dumps(
                {
                    "refusal": envelope,
                    "beforeRestart": cancelled,
                    "afterRestart": after,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    finally:
        await browser.close()
