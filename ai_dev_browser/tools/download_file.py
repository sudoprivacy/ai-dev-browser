"""Download a file."""

from ai_dev_browser.core import download_file as core_download
from ._cli import as_cli


@as_cli()
async def download_file(tab, url: str, path: str) -> dict:
    """Download a file.

    Args:
        tab: Browser tab
        url: URL to download
        path: Local path to save
    """
    try:
        await core_download(tab, url=url, output=path)
        return {"downloaded": True, "url": url, "path": path}
    except Exception as e:
        return {"error": f"Download failed: {e}"}


if __name__ == "__main__":
    download_file.cli_main()
