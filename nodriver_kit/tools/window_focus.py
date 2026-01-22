"""Bring browser window to front.

CLI:
    python -m nodriver_kit.tools.window_focus

Python:
    from nodriver_kit.tools import window_focus
    result = await window_focus(tab)
"""

from ._cli import as_cli


@as_cli()
async def window_focus(tab) -> dict:
    """Bring the browser window to front.

    Useful when the browser window is hidden behind other windows.

    Args:
        tab: Browser tab

    Returns:
        {"focused": True} on success
    """
    try:
        await tab.bring_to_front()
        return {"focused": True}
    except Exception as e:
        return {"error": f"window_focus failed: {e}"}


if __name__ == "__main__":
    window_focus.cli_main()
