"""Get page info.

CLI:
    python -m nodriver_kit.tools.page_info

Python:
    from nodriver_kit.tools import page_info
    result = await page_info(tab)
"""

from nodriver_kit.core import get_page_info
from ._cli import as_cli


@as_cli()
async def page_info(tab) -> dict:
    """Get current page information.

    Args:
        tab: Browser tab

    Returns:
        {"url": ..., "title": ..., "ready": ..., "state": ...}
    """
    try:
        return await get_page_info(tab)
    except Exception as e:
        return {"error": f"Get page info failed: {e}"}


if __name__ == "__main__":
    page_info.cli_main()
