"""Read actual owned synthetic files through the existing SDK Chrome/CDP."""

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import aiohttp
from aiohttp import web

from ai_dev_browser.core import _session
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser
from ai_dev_browser.remote.files import BrowserFiles
from ai_dev_browser.remote.session import BrowserSession


async def test_owned_short_long_and_native_prefix_file_paths(tmp_path, monkeypatch):
    async def form(request):
        return web.Response(
            text='<input id="file" type="file">', content_type="text/html"
        )

    app = web.Application()
    app.router.add_get("/", form)

    async def download(request):
        return web.Response(
            body=b"original owned file",
            headers={
                "Content-Disposition": 'attachment; filename="'
                + request.match_info["name"]
                + '"'
            },
            content_type="application/octet-stream",
        )

    app.router.add_get("/download/{name}", download)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/"
    browser = launched = session = None
    results = []
    downloads = []
    with tempfile.TemporaryDirectory(prefix="adb-file-") as private:
        private = Path(private)
        monkeypatch.setattr(_session, "_DIR", private / "sessions")
        try:
            launched = await asyncio.to_thread(
                browser_start,
                headless=True,
                temp=True,
                stealth=False,
                transport="cdp",
                url=url,
                chrome_path=os.environ.get("AI_DEV_BROWSER_CHROME"),
                silent_stderr=True,
                extra_args=["--no-sandbox"] if sys.platform == "linux" else [],
            )
            assert "error" not in launched
            browser = await connect_browser(session_id=launched["session_id"])
            async with aiohttp.ClientSession() as http:
                session = BrowserSession(browser, http)
                await session.state()
                page = await session._connect_page()
                document = (await page.call("DOM.getDocument"))["root"]["nodeId"]
                node = (
                    await page.call(
                        "DOM.querySelector", {"nodeId": document, "selector": "#file"}
                    )
                )["nodeId"]
                short = BrowserFiles(private / "short")
                long = BrowserFiles(
                    private
                    / ("directory-1234567890" * 3)
                    / ("directory-1234567890" * 3)
                    / ("directory-1234567890" * 3)
                )
                for label, store in [("short", short), ("long", long)]:
                    item = store.receive("original.txt", b"original owned file")
                    path = store.path(item["id"], kind="upload")
                    variants = [("plain", str(path))]
                    if sys.platform == "win32":
                        variants.append(("extended", "\\\\?\\" + str(path)))
                    variants.append(
                        ("sdk", store.browser_path(item["id"], kind="upload"))
                    )
                    for mode, physical in variants:
                        await page.call(
                            "DOM.setFileInputFiles",
                            {"nodeId": node, "files": [physical]},
                        )
                        observed = await page.js(
                            "(async()=>{const f=document.querySelector('#file').files[0];try{return {bytes:f?.size,text:await f.text()}}catch(e){return {bytes:f?.size,error:e.name}}})()"
                        )
                        results.append(
                            {
                                "case": label,
                                "mode": mode,
                                "pathChars": len(physical),
                                "pythonBytes": path.stat().st_size,
                                "browserBytes": observed.get("bytes"),
                                "error": observed.get("error"),
                                "contentExact": observed.get("text")
                                == "original owned file",
                            }
                        )
                browser_cdp = await session._connect_browser()
                for label, store in [("short", short), ("long", long)]:
                    directory = str(store.downloads)
                    for mode, destination in [
                        ("plain", directory),
                        *(
                            [("extended", "\\\\?\\" + directory)]
                            if sys.platform == "win32"
                            else []
                        ),
                    ]:
                        name = (
                            "original-complete-filename-" + label + "-" + mode + ".txt"
                        )
                        await browser_cdp.call(
                            "Browser.setDownloadBehavior",
                            {
                                "behavior": "allow",
                                "downloadPath": destination,
                                "eventsEnabled": True,
                            },
                        )
                        await page.call(
                            "Page.navigate", {"url": url + "download/" + name}
                        )
                        deadline = time.monotonic() + 5
                        found = None
                        while time.monotonic() < deadline:
                            values = await asyncio.to_thread(
                                store.collect_downloads, settle_seconds=0
                            )
                            found = next(
                                (value for value in values if mode in value["name"]),
                                None,
                            )
                            if found:
                                break
                            await asyncio.sleep(0.05)
                        downloads.append(
                            {
                                "case": label,
                                "mode": mode,
                                "directoryChars": len(destination),
                                "arrived": found is not None,
                                "fullNameExact": found is not None
                                and found["name"] == name,
                                "bytes": found["bytes"] if found else None,
                            }
                        )
                (tmp_path / "owned-file-path-observations.json").write_text(
                    json.dumps(
                        {
                            "results": results,
                            "downloads": downloads,
                            "fixtureFilesAndGrantScope": True,
                            "productionAcceptance": False,
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                assert next(
                    item
                    for item in results
                    if item["case"] == "short" and item["mode"] == "plain"
                )["contentExact"]
                if sys.platform != "win32":
                    assert all(item["contentExact"] for item in results)
                assert all(
                    item["contentExact"] and item["browserBytes"] == item["pythonBytes"]
                    for item in results
                    if item["mode"] == "sdk"
                )
                await session.close()
                session = None
        finally:
            if session:
                await session.close()
            if browser:
                await browser.close()
            if launched and launched.get("session_id"):
                result = await asyncio.to_thread(
                    browser_stop, session_id=launched["session_id"]
                )
                assert result.get("stopped") is True
            await runner.cleanup()
