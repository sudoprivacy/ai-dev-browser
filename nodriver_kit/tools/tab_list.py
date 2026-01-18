"""List open tabs.

CLI:
    python -m nodriver_kit.tools.tab_list

Python:
    from nodriver_kit.tools import tab_list
    result = await tab_list(tab)
"""

from nodriver_kit.core import list_tabs
from ._cli import as_cli


@as_cli
async def tab_list(tab) -> dict:
    """List all open tabs.

    Args:
        tab: Browser tab

    Returns:
        {"tabs": [...], "count": ...}
    """
    try:
        tabs = await list_tabs(tab)
        return {
            "tabs": tabs,
            "count": len(tabs),
        }
    except Exception as e:
        return {"error": f"List tabs failed: {e}"}


if __name__ == "__main__":
    tab_list.cli_main()
