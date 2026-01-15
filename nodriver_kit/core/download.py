"""Download operations."""

from pathlib import Path
from typing import Optional, Union

import nodriver


async def set_download_path(
    tab: nodriver.Tab,
    path: Union[str, Path],
) -> Path:
    """Set download directory.

    Args:
        tab: Tab instance
        path: Download directory path

    Returns:
        Resolved path
    """
    resolved = Path(path).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    await tab.set_download_path(str(resolved))
    return resolved


async def download_file(
    tab: nodriver.Tab,
    url: str,
    output: Optional[Union[str, Path]] = None,
) -> Optional[Path]:
    """Download a file.

    Args:
        tab: Tab instance
        url: URL to download
        output: Output file path (default: auto)

    Returns:
        Path to downloaded file
    """
    output_path = None
    if output:
        output_path = Path(output).expanduser().resolve()

    result = await tab.download_file(url, output_path)
    return Path(result) if result else None
