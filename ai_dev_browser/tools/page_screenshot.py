"""Take a screenshot of the page."""

import tempfile
from pathlib import Path

from .._cli import as_cli


@as_cli()
async def page_screenshot(tab, path: str = None, full_page: bool = False) -> dict:
    """Take a screenshot of the page.

    Args:
        tab: Browser tab
        path: Path to save screenshot (optional, uses temp file if not provided)
        full_page: If True, capture full page (not just viewport)
    """
    try:
        if path is None:
            path = tempfile.mktemp(suffix=".png")

        await tab.save_screenshot(path, full_page=full_page)

        file_size = Path(path).stat().st_size
        return {
            "path": path,
            "size": file_size,
            "success": True,
        }
    except Exception as e:
        return {"error": f"Screenshot failed: {e}"}


if __name__ == "__main__":
    page_screenshot.cli_main()
