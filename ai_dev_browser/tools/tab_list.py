"""List open tabs.

CLI:
    python -m ai_dev_browser.tools.tab_list

Python:
    from ai_dev_browser.tools import tab_list
    result = await tab_list(tab)
"""

from ai_dev_browser.core import list_tabs
from ._cli import as_cli


@as_cli()
async def tab_list(tab) -> dict:
    """List all open tabs.

    Args:
        tab: Browser tab

    Returns:
        {"tabs": [...], "count": ...}
    """
    try:
        tabs = list_tabs(tab)
        return {
            "tabs": tabs,
            "count": len(tabs),
        }
    except Exception as e:
        return {"error": f"List tabs failed: {e}"}


if __name__ == "__main__":
    tab_list.cli_main()
