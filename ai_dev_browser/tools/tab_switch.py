"""Switch to a tab."""

from ai_dev_browser.core import switch_tab

from .._cli import as_cli


@as_cli()
async def tab_switch(tab, id: int) -> dict:
    """Switch to a tab by id.

    Args:
        tab: Browser tab
        id: Tab id (from tab_list output)
    """
    try:
        await switch_tab(tab, tab_id=id)
        return {"switched": True, "id": id}
    except Exception as e:
        return {"error": f"tab_switch failed: {e}"}


if __name__ == "__main__":
    tab_switch.cli_main()
