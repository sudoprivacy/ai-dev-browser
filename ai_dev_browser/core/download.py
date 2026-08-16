"""Download operations."""

import asyncio
from pathlib import Path

from ai_dev_browser.cdp import browser as cdp_browser

from ._tab import Tab
from .elements import _trusted_click, _xpath_finder_js


async def download(
    tab: Tab,
    url: str,
    path: str | Path | None = None,
) -> dict:
    """Download a file from URL.

    Sets the download directory (if path provided) and triggers the download.

    Args:
        tab: Tab instance
        url: URL to download
        path: Download directory or file path (default: ./downloads/)

    Returns:
        dict with path and success status
    """
    if path:
        download_dir = Path(path).expanduser().resolve()
        if download_dir.is_dir() or not download_dir.suffix:
            download_dir.mkdir(parents=True, exist_ok=True)
            await tab.download_path(str(download_dir))
    else:
        default_dir = Path.cwd() / "downloads"
        default_dir.mkdir(parents=True, exist_ok=True)
        await tab.download_path(str(default_dir))

    result = await tab.download_file(url)
    if result:
        return {"path": str(result), "success": True}
    return {"path": None, "success": False}


async def download_link(
    tab: Tab,
    xpath: str,
    download_dir: str | None = None,
    timeout: float = 30.0,
) -> dict:
    """Use when: clicking a link/button starts a file download and you want the
    saved path back — batch scraping, where you iterate rows and download each
    without hand-counting the Downloads folder. Unlike `download` (which needs
    the file's URL), this drives the real control: locate it by XPath (the
    reliable locator for the unnamed download links common in Chinese gov /
    enterprise SPAs), trusted-click it, wait for the file to finish, and return
    where it landed.

    Returns `{downloaded: True, path, filename, bytes}` on success, or
    `{downloaded: False, error, clicked?}` so you can tell "link not found"
    (`clicked` absent) from "clicked but nothing downloaded" (`clicked: True`).

    Args:
        tab: Tab instance
        xpath: XPath of the download link / button (e.g.
            `//tr[td[contains(.,'2025')]]//a[contains(.,'下载')]`).
        download_dir: Directory to save into (default: `./downloads`, created
            if missing).
        timeout: Seconds to wait for the download to complete (default 30).

    Returns:
        dict: `{downloaded, path, filename, bytes}` or `{downloaded: False,
        error, clicked?}`.

    Failure:
        `clicked: True` but no download completed in time — the link may open a
        viewer/new tab instead of downloading, or it fired a `confirm()` that
        needs `AI_DEV_BROWSER_DIALOG=accept`, or the file is large (raise
        `timeout`). Without `clicked`, the XPath matched nothing — verify with
        `find_by_xpath`.
    """
    directory = Path(download_dir) if download_dir else (Path.cwd() / "downloads")
    directory.mkdir(parents=True, exist_ok=True)
    dir_str = str(directory.resolve())

    # allow + eventsEnabled so downloadWillBegin / downloadProgress fire (under
    # automation Chrome otherwise denies the download and stays silent).
    await tab.send(
        cdp_browser.set_download_behavior(
            behavior="allow", download_path=dir_str, events_enabled=True
        )
    )

    done = asyncio.Event()
    cap: dict = {
        "guid": None,
        "filename": None,
        "path": None,
        "bytes": None,
        "state": None,
    }

    def on_begin(e: cdp_browser.DownloadWillBegin) -> None:
        # Bind to the first download the click triggers; ignore any others.
        if cap["guid"] is None:
            cap["guid"] = e.guid
            cap["filename"] = e.suggested_filename

    def on_progress(e: cdp_browser.DownloadProgress) -> None:
        if cap["guid"] is not None and e.guid != cap["guid"]:
            return
        cap["state"] = e.state
        if e.state == "completed":
            cap["path"] = e.file_path  # may be None on some platforms
            cap["bytes"] = e.received_bytes
            done.set()
        elif e.state == "canceled":
            done.set()

    tab.add_handler(cdp_browser.DownloadWillBegin, on_begin)
    tab.add_handler(cdp_browser.DownloadProgress, on_progress)
    try:
        click = await _trusted_click(tab, _xpath_finder_js(xpath), "xpath", xpath)
        if not click.get("clicked"):
            return {
                "downloaded": False,
                "xpath": xpath,
                "error": click.get("error", "download link not found"),
            }
        try:
            await asyncio.wait_for(done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return {
                "downloaded": False,
                "xpath": xpath,
                "clicked": True,
                "error": f"clicked, but no download completed within {timeout}s",
            }
        if cap["state"] != "completed":
            return {
                "downloaded": False,
                "xpath": xpath,
                "clicked": True,
                "error": f"download {cap['state']}",
            }
        # file_path from the event when set; else the suggested name in our dir.
        path = cap["path"] or str(directory / (cap["filename"] or ""))
        return {
            "downloaded": True,
            "xpath": xpath,
            "path": path,
            "filename": cap["filename"],
            "bytes": cap["bytes"],
        }
    finally:
        tab.remove_handler(cdp_browser.DownloadWillBegin, on_begin)
        tab.remove_handler(cdp_browser.DownloadProgress, on_progress)
