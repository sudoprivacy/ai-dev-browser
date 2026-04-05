"""Download operations."""

from pathlib import Path

from ._tab import Tab


async def download_path(
    tab: Tab,
    path: str | Path,
) -> dict:
    """Set download directory.

    Args:
        tab: Tab instance
        path: Download directory path

    Returns:
        dict with resolved path
    """
    resolved = Path(path).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    await tab.download_path(str(resolved))
    return {"path": str(resolved)}


async def download_file(
    tab: Tab,
    url: str,
    path: str | Path | None = None,
) -> dict:
    """Download a file.

    Args:
        tab: Tab instance
        url: URL to download
        path: Output file path (default: auto)

    Returns:
        dict with path and success status
    """
    output_path = None
    if path:
        output_path = Path(path).expanduser().resolve()

    result = await tab.download_file(url, output_path)
    if result:
        return {"path": str(result), "success": True}
    return {"path": None, "success": False}
