"""Real extension upgrade: unknown runtime -> ordinary reload -> trusted input."""

import asyncio
import json
import logging
import shutil
import time

from aiohttp import web
import psutil

from ai_dev_browser import cdp
from ai_dev_browser.core import (
    click_by_html_id,
    connect_browser,
    js_evaluate,
    page_goto,
    page_screenshot,
    type_by_text,
    window_set,
)
from ai_dev_browser.core.extension import extension_dir, extension_version_info
from .extension_window_support import extension_cli


async def _reload_in_manager(observer, extension_id):
    """Use the fixture Chrome's ordinary Developer mode and Reload controls."""
    manager = await observer.get("chrome://extensions/", tab_new=True)
    enabled = await manager.evaluate("""(() => {
      const manager = document.querySelector('extensions-manager');
      const toolbar = manager?.shadowRoot.querySelector('extensions-toolbar');
      const toggle = toolbar?.shadowRoot.querySelector('#devMode');
      if (!toggle) return false;
      if (!toggle.checked) toggle.click();
      return toggle.checked;
    })()""")
    assert enabled, "The normal Developer mode control must be available"
    find_button = """(() => {
      const manager = document.querySelector('extensions-manager');
      const list = manager?.shadowRoot.querySelector('extensions-item-list');
      const item = list?.shadowRoot.getElementById(%s);
      return item?.shadowRoot.querySelector('#dev-reload-button');
    })()""" % json.dumps(extension_id)
    deadline = time.monotonic() + 10
    while not await manager.evaluate(
        f"Boolean(({find_button})?.getBoundingClientRect().width)"
    ):
        assert time.monotonic() < deadline, (
            "The identified extension's Reload control must become visible"
        )
        await asyncio.sleep(0.05)
    assert await manager.evaluate(
        f"(() => {{ const button = {find_button}; if (!button || button.disabled) return false; button.click(); return true; }})()"
    )


async def runtime_upgrade_journey(extension, root, caplog):
    caplog.set_level(logging.INFO, logger="ai_dev_browser.core.ext_bridge")
    start = len(caplog.records)
    receipts = []
    history = []

    async def form(request):
        return web.Response(
            content_type="text/html",
            text="""<!doctype html><meta charset="utf-8"><title>Runtime upgrade acceptance</title>
<style>body{font:24px sans-serif;padding:36px;background:#eef2f7}input,button{font:inherit;padding:12px}</style>
<h1>Runtime upgrade acceptance</h1><label>Request name <input id="name"></label><button id="submit">Submit once</button><pre id="result">Waiting</pre>
<script>window.inputTrust=[];document.querySelector('#name').oninput=e=>inputTrust.push(e.isTrusted);document.querySelector('#submit').onclick=async e=>{const receipt={name:document.querySelector('#name').value,trusted:e.isTrusted};await fetch('/receipt',{method:'POST',body:JSON.stringify(receipt)});document.querySelector('#result').textContent=JSON.stringify(receipt)}</script>""",
        )

    async def receive(request):
        receipts.append(await request.json())
        return web.json_response({"saved": True})

    app = web.Application()
    app.router.add_get("/{page}", form)
    app.router.add_post("/receipt", receive)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    origin = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    observer = None
    try:
        await extension.call(page_goto, url=origin + "/before")
        code, before = await extension_cli(extension, "browser_connect")
        assert code == 0 and before["connected"]
        assert before["extension_version"] is None
        assert before["extension_version_matches_bundle"] is None
        assert "unknown" in before["extension_warning"]
        assert "Before page input" in before["extension_warning"]
        assert "chrome://extensions" in before["extension_warning"]
        assert str(extension_dir()) in before["extension_warning"]
        history.append({"unknown_connection": before})
        code, refusal = await extension_cli(
            extension, "window_set", "--state", "normal"
        )
        assert code == 6 and refusal["error_code"] == "unsupported"
        assert refusal["details"]["input_sent"] is False
        assert refusal["details"]["extension_version_matches_bundle"] is None
        history.append({"unsupported_window": refusal})

        # Setup/independent observer only: this is the fixture's isolated Chrome.
        # All application navigation/input under test continues through extension.
        observer = await connect_browser(port=extension.chrome_port)
        unrelated = await observer.get(origin + "/unrelated", tab_new=True)
        original_tabs = {
            str(tab.target_id)
            for tab in await observer.connection.send(cdp.target.get_targets())
            if tab.type_ == "page"
        }
        assert str(unrelated._target.target_id) != before["automation_target_id"]
        born = psutil.Process(extension.chrome_pid).create_time()
        worker = None
        for candidate in observer.targets:
            if candidate.type_ != "service_worker":
                continue
            try:
                value, error = await candidate._connection.send(
                    cdp.runtime.evaluate(
                        "typeof BRIDGE === 'string' ? BRIDGE : null",
                        return_by_value=True,
                    )
                )
                if error is None and value.value == f"ws://127.0.0.1:{extension.port}":
                    worker = candidate
                    break
            finally:
                if worker is not candidate:
                    await candidate._connection.disconnect()
        assert worker is not None, "Owned fixture extension worker not found"
        try:
            extension_id = worker.target.url.split("/")[2]
            destination = root / "extension"
            shutil.copytree(extension_dir(), destination, dirs_exist_ok=True)
            background = destination / "background.js"
            source = background.read_text(encoding="utf-8")
            assert source.count("127.0.0.1:9522") == 1
            background.write_text(
                source.replace("127.0.0.1:9522", f"127.0.0.1:{extension.port}"),
                encoding="utf-8",
            )
        finally:
            await worker._connection.disconnect()
        await _reload_in_manager(observer, extension_id)
        expected = extension_version_info(None)["bundled_extension_version"]
        deadline = time.monotonic() + 10
        try:
            while extension.bridge.identity.get("extension_version") != expected:
                assert time.monotonic() < deadline, (
                    "Updated fixture did not reconnect after ordinary reload"
                )
                await asyncio.sleep(0.05)
        finally:
            history.append(
                {
                    "reload_observation": {
                        "connected": extension.bridge.extension is not None,
                        "reported_version": extension.bridge.identity.get(
                            "extension_version"
                        ),
                        "expected_version": expected,
                    }
                }
            )
        assert psutil.Process(extension.chrome_pid).create_time() == born
        current_tabs = {
            str(tab.target_id)
            for tab in await observer.connection.send(cdp.target.get_targets())
            if tab.type_ == "page"
        }
        assert original_tabs.issubset(current_tabs)
        code, stale = await extension_cli(
            extension, "browser_connect", "--session-id", before["session_id"]
        )
        assert code == 5 and stale["error_code"] == "session_changed"
        code, after = await extension_cli(extension, "browser_connect")
        assert code == 0 and after["connected"]
        assert after["profile_id"] == before["profile_id"]
        assert after["session_id"] != before["session_id"]
        assert after["extension_version"] == expected
        assert after["extension_version_matches_bundle"] is True
        assert after["extension_warning"] is None
        assert after["automation_target_id"] not in original_tabs
        history.append(
            {
                "verified_connection": after,
                "stale_session": stale,
                "original_tabs_preserved": True,
                "chrome_process_preserved": True,
            }
        )
        commands = [
            record.args[0]
            for record in caplog.records[start:]
            if record.name == "ai_dev_browser.core.ext_bridge"
            and record.msg == "action: %s%s"
            and record.args[0].startswith("Input.")
        ]
        assert commands == [] and receipts == []
        history.append({"input_commands_before_runtime_verification": commands})
        await extension.call(page_goto, url=origin + "/after")
        window = await extension.call(window_set, state="normal", focus=True)
        assert (
            window["state"] == "normal"
            and window["visibility"] == "visible"
            and window["input_ready"]
        )
        typed = await extension.call(
            type_by_text, name="Request name", text="Runtime upgrade accepted"
        )
        assert typed["typed"] and typed["verified"] and typed["method"] != "native"
        trust = (await extension.call(js_evaluate, expression="window.inputTrust"))[
            "result"
        ]
        assert trust and all(trust)
        assert (await extension.call(click_by_html_id, html_id="submit"))["clicked"]
        assert receipts == [{"name": "Runtime upgrade accepted", "trusted": True}]
        await extension.call(
            page_screenshot, path=str(root / "runtime-upgrade-accepted.png")
        )
        history.append(
            {"window": window, "trusted_input_events": trust, "receipts": receipts}
        )
    finally:
        (root / "runtime-upgrade-evidence.json").write_text(
            json.dumps(history, indent=2), encoding="utf-8"
        )
        if observer is not None:
            await observer.close()
        await runner.cleanup()
