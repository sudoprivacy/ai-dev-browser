"""Neutral local-form acceptance for ordinary extension window visibility."""

import asyncio
import json
import logging
import os
import sys
import time

from aiohttp import web
import psutil
import pytest

from ai_dev_browser.core import (
    cdp_send,
    click_by_html_id,
    connect_browser,
    js_evaluate,
    mouse_click,
    page_goto,
    page_screenshot,
    type_by_text,
    type_by_ref,
    page_wait_element,
    window_set,
)
from ai_dev_browser.core.errors import InputUnavailableError
from ai_dev_browser.core._transport import ProtocolException
from .native_window_occluder import visible_owned_window, cover_with_fixture_window


async def extension_cli(extension, tool, *flags):
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("AI_DEV_BROWSER_")
    }
    environment.update(
        AI_DEV_BROWSER_EXTENSION_BRIDGE_PORT=str(extension.port), PYTHONUTF8="1"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        f"ai_dev_browser.tools.{tool}",
        "--transport",
        "extension",
        *map(str, flags),
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    assert stdout.strip(), stderr
    return process.returncode, json.loads(stdout)


async def windowless_startup_journey(extension, site, root):
    """Use the real extension-owned window created before CDP's first page."""
    order = json.loads((root / "windowless-startup-order.json").read_text())
    assert order["hello_received"] and order["owned_target_before_cdp_creation"]
    status, connection = await extension_cli(extension, "browser_connect")
    assert status == 0 and connection["extension_version_matches_bundle"] is True
    assert connection["extension_warning"] is None
    assert connection["extension_version"] == order["extension_version"]
    await extension.call(page_goto, url=site[0])
    state = await extension.call(window_set, state="normal", focus=True)
    assert state["input_ready"] and state["visibility"] == "visible", state
    await extension.call(
        js_evaluate,
        expression="window.inputTrust=[];document.querySelector('#name').addEventListener('input',e=>inputTrust.push(e.isTrusted));true",
    )
    field = await extension.call(page_wait_element, selector="#name")
    typed = await extension.call(
        type_by_ref, ref=field["ref"], text="Windowless startup accepted"
    )
    assert typed["verified"] and typed["method"] != "native"
    trust = (await extension.call(js_evaluate, expression="window.inputTrust"))[
        "result"
    ]
    assert trust and all(trust)
    assert (await extension.call(click_by_html_id, html_id="submit"))["clicked"]
    deadline = time.monotonic() + 10
    while not site[1]:
        assert time.monotonic() < deadline
        await asyncio.sleep(0.01)
    assert site[1] == [
        {
            "name": "Windowless startup accepted",
            "trusted": True,
            "press": {"buttons": 1, "trusted": True},
            "cookie": "isolated",
            "sequence": 1,
        }
    ]
    await extension.call(
        page_screenshot, path=str(root / "windowless-extension-accepted.png")
    )
    (root / "windowless-extension-evidence.json").write_text(
        json.dumps(
            {
                "startup": order,
                "window": state,
                "trusted_input": trust,
                "receipts": site[1],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


async def window_visibility_journey(extension, root, caplog):
    caplog.set_level(logging.INFO, logger="ai_dev_browser.core.ext_bridge")
    receipts = []
    history = []
    title = "ADB neutral native visibility"

    async def page(request):
        return web.Response(
            text=f"""<!doctype html><meta charset="utf-8"><title>{title if request.path == "/" else "Unrelated neutral window"}</title>
<style>body{{font:24px sans-serif;background:#eef2f7;padding:32px}}input,button{{font:inherit;padding:14px}}pre{{white-space:pre-wrap}}</style>
<h1>Native window acceptance</h1><label>Request name <input id="name"></label>
<button id="submit">Submit once</button><pre id="result">No input received</pre>
<script>window.inputEvents=[];
['mousedown','mouseup','click','keydown','input'].forEach(type=>document.addEventListener(type,e=>inputEvents.push({{type,trusted:e.isTrusted,target:e.target.id,tag:e.target.tagName}}),true));
document.querySelector('#submit').onclick=async e=>{{const receipt={{name:document.querySelector('#name').value,trusted:e.isTrusted}};await fetch('/receipt',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(receipt)}});document.querySelector('#result').textContent=JSON.stringify(receipt)}};
</script>""",
            content_type="text/html",
        )

    async def receipt(request):
        receipts.append(await request.json())
        return web.json_response({"saved": True})

    app = web.Application()
    app.router.add_get("/", page)
    app.router.add_get("/unrelated", page)
    app.router.add_post("/receipt", receipt)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"

    async def state():
        return (
            await extension.call(
                js_evaluate,
                tab_url=url + "/",
                expression="({visibility:document.visibilityState,focused:document.hasFocus(),value:document.querySelector('#name').value,events:inputEvents})",
            )
        )["result"]

    async def visible(expected):
        deadline = time.monotonic() + 5
        while True:
            observed = await state()
            if (observed["visibility"] == "visible") == expected:
                return observed
            assert time.monotonic() < deadline, observed
            await asyncio.sleep(0.05)

    try:
        args = psutil.Process(extension.chrome_pid).cmdline()
        assert "--disable-backgrounding-occluded-windows" not in args
        await extension.call(page_goto, url=url + "/")
        code, connected = await extension_cli(extension, "browser_connect")
        assert code == 0 and connected["connected"]
        assert connected["extension_version_matches_bundle"] is True
        history.append(
            {
                "loaded_extension": {
                    key: connected[key]
                    for key in (
                        "extension_version",
                        "bundled_extension_version",
                        "extension_version_matches_bundle",
                    )
                }
            }
        )
        minimized = await extension.call(
            window_set, tab_url=url + "/", state="minimized"
        )
        assert minimized["state"] == "minimized" and not minimized["input_ready"]
        restored = await extension.call(
            window_set, tab_url=url + "/", state="normal", focus=True
        )
        assert restored["state"] == "normal"
        observed = await state()
        assert restored["visibility"] == observed["visibility"]
        history.append({"minimized": minimized, "restored": restored})

        # Create an unrelated second window through the owned fixture's setup
        # connection. All form input and window operations under test use extension.
        setup = await connect_browser(port=extension.chrome_port)
        try:
            other = await setup.get(url + "/unrelated", tab_new=True, new_window=True)
            foreign_id, before = await other.get_window()
            for method, params in (
                ("Browser.getWindowBounds", {"windowId": foreign_id}),
                (
                    "Browser.setWindowBounds",
                    {"windowId": foreign_id, "bounds": {"windowState": "minimized"}},
                ),
            ):
                with pytest.raises(
                    ProtocolException,
                    match="does not contain the selected automation tab",
                ):
                    await extension.call(
                        cdp_send,
                        tab_url=url + "/",
                        method=method,
                        params=json.dumps(params),
                    )
            _, after = await other.get_window()
            assert before.window_state == after.window_state
        finally:
            await setup.close()
        await extension.call(window_set, tab_url=url + "/", state="normal", focus=True)

        with visible_owned_window(extension.chrome_pid, title) as handle:
            await visible(True)
            with cover_with_fixture_window(
                extension.chrome_pid, handle, "Unrelated neutral window"
            ):
                await _hidden_refusals(
                    extension, url, state, visible, history, receipts, caplog
                )
            await visible(True)
            typed = await extension.call(
                type_by_text,
                tab_url=url + "/",
                name="Request name",
                text="one visible request",
            )
            assert typed["typed"] and typed["verified"] and typed["method"] != "native"
            clicked = await extension.call(
                click_by_html_id, tab_url=url + "/", html_id="submit"
            )
            assert clicked["clicked"]
            final = await state()
            assert receipts == [{"name": "one visible request", "trusted": True}]
            assert all(event["trusted"] for event in final["events"])
            await extension.call(
                page_screenshot,
                tab_url=url + "/",
                path=str(root / "native-window-accepted.png"),
            )
            history.append({"final": final, "receipts": receipts})
    finally:
        (root / "native-window-evidence.json").write_text(
            json.dumps(history, indent=2), encoding="utf-8"
        )
        await runner.cleanup()


async def _hidden_refusals(extension, url, state, visible, history, receipts, caplog):
    hidden = await visible(False)
    hidden_result = await extension.call(
        window_set, tab_url=url + "/", state="normal", focus=True
    )
    assert hidden_result["visibility"] == "hidden" and not hidden_result["input_ready"]
    assert (
        hidden_result["success"] is False
        and hidden_result["error_code"] == "unsupported"
    )
    history.append({"occluded": hidden, "focus_result": hidden_result})
    code, cli_focus = await extension_cli(
        extension, "window_set", "--tab-url", url + "/", "--state", "normal", "--focus"
    )
    assert (
        code == 0
        and cli_focus["success"] is False
        and cli_focus["input_ready"] is False
    )
    assert "hint" in cli_focus and cli_focus["retryable"] is False
    start = len(caplog.records)

    for function, options in (
        (type_by_text, {"name": "Request name", "text": "must stay empty"}),
        (mouse_click, {"x": 60, "y": 60, "move": True, "human_like": False}),
        (click_by_html_id, {"html_id": "submit"}),
    ):
        with pytest.raises(InputUnavailableError) as caught:
            await extension.call(function, tab_url=url + "/", **options)
        error = caught.value
        assert error.error_code == "unsupported" and error.retryable is False
        assert (
            error.details["visibility"] == "hidden"
            and error.details["input_sent"] is False
        )
        assert error.details["extension_version_matches_bundle"] is True
        history.append({"refused": function.__name__, "details": error.details})
    untouched = await state()
    assert untouched["value"] == "" and receipts == []
    assert not any(
        event["target"] in {"name", "submit"} for event in untouched["events"]
    )
    code, refused = await extension_cli(
        extension,
        "type_by_text",
        "--tab-url",
        url + "/",
        "--name",
        "Request name",
        "--text",
        "must stay empty",
    )
    assert (
        code == 6
        and refused["error_code"] == "unsupported"
        and refused["retryable"] is False
    )
    assert (
        refused["details"]["input_sent"] is False
        and refused["details"]["visibility"] == "hidden"
    )
    assert (
        "chrome://extensions" in refused["hint"] and "was not sent" in refused["error"]
    )
    after = await state()
    dispatched = [
        record.args[0]
        for record in caplog.records[start:]
        if record.name == "ai_dev_browser.core.ext_bridge"
        and record.msg == "action: %s%s"
        and record.args[0].startswith("Input.")
    ]
    # A recheck observed native keydown events before the attempted action.
    # Preserve them in evidence; the actual bridge command ledger and
    # form-control effects identify whether adb dispatched input.
    history.append(
        {
            "cli_refusal": refused,
            "window_cli": cli_focus,
            "all_page_events": after["events"],
            "input_commands_during_refusal": dispatched,
        }
    )
    assert dispatched == [] and after["value"] == "" and receipts == []
    assert not any(event["target"] in {"name", "submit"} for event in after["events"])


async def previous_extension_journey(extension, root):
    code, connection = await extension_cli(extension, "browser_connect")
    assert code == 0 and connection["connected"]
    assert (
        connection["extension_version"]
        and connection["extension_version_matches_bundle"] is False
    )
    assert "Before page input" in connection["extension_warning"]
    assert "chrome://extensions" in connection["extension_warning"]
    assert connection["extension_version"] in connection["extension_warning"]
    code, refused = await extension_cli(extension, "window_set", "--state", "normal")
    assert code == 6 and refused["error_code"] == "unsupported"
    assert (
        "Browser.setWindowBounds" in refused["error"]
        and "chrome://extensions" in refused["hint"]
    )
    assert refused["details"]["input_sent"] is False
    assert refused["details"]["extension_version"] == connection["extension_version"]
    assert refused["details"]["extension_version_matches_bundle"] is False
    (root / "previous-extension-evidence.json").write_text(
        json.dumps(refused, indent=2), encoding="utf-8"
    )
