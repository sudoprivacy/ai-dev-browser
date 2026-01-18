"""Switch to a tab.

CLI:
    python -m nodriver_kit.tools.tab_switch --index 1

Python:
    from nodriver_kit.tools import tab_switch
    result = await tab_switch(tab, index=1)
"""

from nodriver_kit.core import switch_tab
from ._cli import as_cli


@as_cli
async def tab_switch(tab, index: int) -> dict:
    """Switch to a tab by index.

    Args:
        tab: Browser tab
        index: Tab index (0-based)

    Returns:
        {"switched": True, "index": ...}
    """
    try:
        await switch_tab(tab, index=index)
        return {"switched": True, "index": index}
    except Exception as e:
        return {"error": f"Switch tab failed: {e}"}


if __name__ == "__main__":
    tab_switch.cli_main()
