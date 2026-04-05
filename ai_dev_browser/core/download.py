"""Download operations."""

from pathlib import Path

from ._tab import Tab


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
