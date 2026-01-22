"""Close a tab.

CLI:
    python -m ai_dev_browser.tools.tab_close --id 1

Python:
    from ai_dev_browser.tools import tab_close
    result = await tab_close(tab, id=1)
"""

from ai_dev_browser.core import close_tab
from ._cli import as_cli


@as_cli()
async def tab_close(tab, id: int = None) -> dict:
    """Close a tab by id.

    Args:
        tab: Browser tab
        id: Tab id to close (from tab_list output)

    Returns:
        {"closed": True, "id": ...}
    """
    try:
        await close_tab(tab, tab_id=id)
        return {"closed": True, "id": id}
    except Exception as e:
        return {"error": f"tab_close failed: {e}"}


if __name__ == "__main__":
    tab_close.cli_main()
