"""Actual Chrome upload and download in one controlled persistent session."""

import asyncio
import base64
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web

from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import (
    connect_browser,
    connect_extension,
    get_active_tab,
)
from ai_dev_browser.remote.control import ControlError
from ai_dev_browser.remote.files import BrowserFiles
from ai_dev_browser.remote.provision import (
    configure_managed_extension_file_access,
    prepare_managed_extension_profile,
)
from ai_dev_browser.remote.session import BrowserSession
from tests.integration.test_remote_view import wait_for


@pytest.mark.parametrize(
    "transport",
    [
        "cdp",
        pytest.param(
            "extension",
            marks=pytest.mark.skipif(
                not os.environ.get("AI_DEV_BROWSER_MANAGED_EXTENSION_PROFILE"),
                reason="Signed managed Chrome fixture required",
            ),
        ),
    ],
)
async def test_real_file_picker_and_download_keep_profile_and_control(
    tmp_path, transport
):
    payload = ("browser file receipt " + uuid.uuid4().hex).encode()
    filename = "report_" + uuid.uuid4().hex[:8] + ".txt"
    receipts = []
    downloads = []
    clicks = []
    protocol_events = []
    html = """<!doctype html><meta charset="utf-8"><title>Browser files</title>
    <style>body{margin:0}input,a{display:block;margin:24px;width:320px;height:48px}</style>
    <input id="upload" type="file"><a id="download" href="/download">Download the receipt</a>
    <script>document.cookie='file_login=present; Path=/; Max-Age=3600';
    upload.onclick=event=>fetch('/clicked',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({trusted:event.isTrusted})});
    upload.onchange=async event=>{const file=upload.files[0];
    await fetch('/receipt',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:file.name,text:await file.text(),trusted:event.isTrusted})});};</script>"""

    async def page(_request):
        return web.Response(text=html, content_type="text/html")

    async def receive(request):
        value = await request.json()
        value["cookie"] = request.cookies.get("file_login")
        receipts.append(value)
        return web.json_response({"received": True})

    async def clicked(request):
        clicks.append(await request.json())
        return web.json_response({"clicked": True})

    async def download(request):
        downloads.append(request.cookies.get("file_login"))
        return web.Response(
            body=payload,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            content_type="application/octet-stream",
        )

    site = web.Application()
    site.add_routes(
        [
            web.get("/", page),
            web.post("/receipt", receive),
            web.post("/clicked", clicked),
            web.get("/download", download),
        ]
    )
    runner = web.AppRunner(site)
    await runner.setup()
    server = web.TCPSite(runner, "127.0.0.1", 0)
    await server.start()
    url = f"http://127.0.0.1:{server._server.sockets[0].getsockname()[1]}/"
    files = BrowserFiles(tmp_path / "files")
    profile = (
        Path(os.environ["AI_DEV_BROWSER_MANAGED_EXTENSION_PROFILE"])
        if transport == "extension"
        else tmp_path / "chrome"
    )
    if transport == "extension":
        identity = json.loads(Path("/opt/browser/extension/identity.json").read_text())
        await prepare_managed_extension_profile(
            str(profile), extension_id=identity["id"], extra_args=["--no-sandbox"]
        )
        await configure_managed_extension_file_access(
            str(profile),
            extension_id=identity["id"],
            enabled=True,
            extra_args=["--no-sandbox"],
        )
    files.configure_managed_profile(profile)
    options = (
        {"transport": "extension", "user_data_dir": str(profile)}
        if transport == "extension"
        else {"profile": str(profile)}
    )
    launched = await asyncio.to_thread(
        browser_start,
        headless=True,
        stealth=False,
        silent_stderr=True,
        extra_args=["--no-sandbox"] if sys.platform == "linux" else [],
        **options,
    )
    assert "error" not in launched, launched
    client = None
    session = None
    try:
        if transport == "extension":
            with pytest.raises(ControlError, match="profile_process_still_running"):
                await configure_managed_extension_file_access(
                    str(profile),
                    extension_id=identity["id"],
                    enabled=True,
                    extra_args=["--no-sandbox"],
                )
        client = await (
            connect_extension(session_id=launched["session_id"])
            if transport == "extension"
            else connect_browser(session_id=launched["session_id"])
        )
        await get_active_tab(client)
        async with aiohttp.ClientSession() as http:
            session = BrowserSession(client, http, files=files)
            initial_target = session.target_id
            assert initial_target == launched["automation_target_id"]
            # Cross-site navigations replace managed Chrome's debugger target.
            # Each navigation must finish on its new document before the very
            # first read, without replaying a navigation or a user operation.
            for destination in [url, url.replace("127.0.0.1", "localhost"), url] * 2:
                await session.action(
                    "ai", 0, 0, {"kind": "navigate", "url": destination}
                )
                assert await session._page.js("!!document.querySelector('#upload')")
            original_event = session._page.on_event

            def on_event(method, params):
                if method == "Page.fileChooserOpened":
                    protocol_events.append(params)
                original_event(method, params)

            session._page.on_event = on_event
            await session.attach("files-view")
            frame = await session.frame("files-view", 0, 0)
            (tmp_path / "files-before-input.jpg").write_bytes(
                base64.b64decode(frame["data"])
            )
            held = await session.take("user", 0, 0)
            epoch = held["controlEpoch"]
            await session.action(
                "user",
                epoch,
                0,
                {"kind": "input", "input": {"kind": "click", "x": 100, "y": 45}},
            )
            chooser = await wait_for(
                lambda: asyncio.sleep(0, result=session.file_chooser()), bool
            )
            upload = files.receive("user review 文件.txt", payload)
            selection = {
                "kind": "upload-files",
                "chooserId": chooser["id"],
                "fileIds": [upload["id"]],
            }
            with pytest.raises(ControlError, match="held_by_user"):
                await session.action("ai", epoch, 0, selection)
            other = BrowserFiles(tmp_path / "other-owner")
            foreign = other.receive("user review 文件.txt", b"foreign")
            with pytest.raises(ControlError, match="not_found"):
                await session.action(
                    "user", epoch, 0, {**selection, "fileIds": [foreign["id"]]}
                )
            with pytest.raises(ControlError, match="chooser_changed"):
                await session.action(
                    "user", epoch, 0, {**selection, "chooserId": uuid.uuid4().hex}
                )
            assert not receipts
            await session.action("user", epoch, 0, selection)
            await wait_for(lambda: asyncio.sleep(0, result=receipts), bool)
            assert receipts == [
                {
                    "name": "user review 文件.txt",
                    "text": payload.decode(),
                    "trusted": True,
                    "cookie": "present",
                }
            ]
            with pytest.raises(ControlError, match="chooser_changed"):
                await session.action("user", epoch, 0, selection)
            await session.action(
                "user",
                epoch,
                0,
                {"kind": "input", "input": {"kind": "click", "x": 100, "y": 115}},
            )
            completed = await wait_for(
                lambda: asyncio.to_thread(files.collect_downloads), bool
            )
            assert len(completed) == 1
            item = completed[0]
            assert item["name"] == filename and item["bytes"] == len(payload)
            assert item["sha256"] == hashlib.sha256(payload).hexdigest()
            assert files.path(item["id"], kind="download").read_bytes() == payload
            assert downloads == ["present"]
            assert session.target_id == initial_target
            resumed, observation = await session.give_back("user", epoch, 0)
            assert (
                resumed["state"] == "ai"
                and observation["activeTargetId"] == initial_target
            )
            evidence = {
                "transport": transport,
                "sameBrowserTarget": initial_target,
                "upload": upload,
                "download": item,
                "trustedChange": True,
                "cookiePreserved": True,
                "aiWriteBlockedWhileHuman": True,
                "foreignFileRejected": True,
                "chooserReplayRejected": True,
            }
            (tmp_path / "browser-files-evidence.json").write_text(
                json.dumps(evidence, indent=2), encoding="utf-8"
            )
            # Retained metadata survives a worker's reconstruction.
            restored = BrowserFiles(tmp_path / "files")
            assert restored.path(upload["id"], kind="upload").read_bytes() == payload
            assert restored.path(item["id"], kind="download").read_bytes() == payload
    except BaseException as error:
        (tmp_path / "files-failure-diagnostics.json").write_text(
            json.dumps(
                {
                    "clicks": clicks,
                    "chooserEvents": protocol_events,
                    "receipts": receipts,
                    "downloadRequests": downloads,
                    "protocolError": getattr(error, "details", None),
                }
            ),
            encoding="utf-8",
        )
        raise
    finally:
        if session:
            await session.close()
        if client:
            await client.close()
        await asyncio.to_thread(browser_stop, session_id=launched["session_id"])
        await runner.cleanup()
