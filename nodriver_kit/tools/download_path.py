"""Set download path.

CLI:
    python -m nodriver_kit.tools.download_path --path "/tmp/downloads"

Python:
    from nodriver_kit.tools import download_path
    result = await download_path(tab, path="/tmp/downloads")
"""

from nodriver_kit.core import set_download_path
from ._cli import as_cli


@as_cli()
async def download_path(tab, path: str) -> dict:
    """Set the download directory.

    Args:
        tab: Browser tab
        path: Download directory path

    Returns:
        {"path": ...}
    """
    try:
        await set_download_path(tab, path=path)
        return {"path": path}
    except Exception as e:
        return {"error": f"Set download path failed: {e}"}


if __name__ == "__main__":
    download_path.cli_main()
