"""Move mouse to coordinates."""

from ai_dev_browser.core import mouse_move as core_mouse_move
from ._cli import as_cli


@as_cli()
async def mouse_move(tab, x: int, y: int) -> dict:
    """Move mouse to coordinates.

    Args:
        tab: Browser tab
        x: X coordinate
        y: Y coordinate
    """
    try:
        await core_mouse_move(tab, x=x, y=y)
        return {"moved": True, "x": x, "y": y}
    except Exception as e:
        return {"error": f"Mouse move failed: {e}"}


if __name__ == "__main__":
    mouse_move.cli_main()
