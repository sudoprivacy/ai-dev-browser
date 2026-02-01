"""Get page info."""

from ai_dev_browser.core import get_page_info

from .._cli import as_cli


@as_cli()
async def page_info(tab) -> dict:
    """Get current page information.

    Args:
        tab: Browser tab
    """
    try:
        return await get_page_info(tab)
    except Exception as e:
        return {"error": f"Get page info failed: {e}"}


if __name__ == "__main__":
    page_info.cli_main()
