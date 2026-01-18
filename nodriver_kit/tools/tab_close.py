"""Close a tab.

CLI:
    python -m nodriver_kit.tools.tab_close --index 1

Python:
    from nodriver_kit.tools import tab_close
    result = await tab_close(tab, index=1)
"""

from nodriver_kit.core import close_tab
from ._cli import as_cli


@as_cli
async def tab_close(tab, index: int = None) -> dict:
    """Close a tab by index.

    Args:
        tab: Browser tab
        index: Tab index to close (default: current tab)

    Returns:
        {"closed": True}
    """
    try:
        await close_tab(tab, index=index)
        return {"closed": True, "index": index}
    except Exception as e:
        return {"error": f"Close tab failed: {e}"}


if __name__ == "__main__":
    tab_close.cli_main()
