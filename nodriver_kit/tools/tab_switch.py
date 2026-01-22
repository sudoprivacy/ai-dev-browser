"""Switch to a tab.

CLI:
    python -m nodriver_kit.tools.tab_switch --id 1

Python:
    from nodriver_kit.tools import tab_switch
    result = await tab_switch(tab, id=1)
"""

from nodriver_kit.core import switch_tab
from ._cli import as_cli


@as_cli()
async def tab_switch(tab, id: int) -> dict:
    """Switch to a tab by id.

    Args:
        tab: Browser tab
        id: Tab id (from tab_list output)

    Returns:
        {"switched": True, "id": ...}
    """
    try:
        await switch_tab(tab, tab_id=id)
        return {"switched": True, "id": id}
    except Exception as e:
        return {"error": f"tab_switch failed: {e}"}


if __name__ == "__main__":
    tab_switch.cli_main()
