"""Bring browser window to front."""

from .._cli import as_cli


@as_cli()
async def window_focus(tab) -> dict:
    """Bring the browser window to front. Useful when hidden behind other windows.

    Args:
        tab: Browser tab
    """
    try:
        await tab.bring_to_front()
        return {"focused": True}
    except Exception as e:
        return {"error": f"window_focus failed: {e}"}


if __name__ == "__main__":
    window_focus.cli_main()
