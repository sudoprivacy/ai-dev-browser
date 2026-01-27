"""Drag mouse from one point to another."""

from ai_dev_browser.core import mouse_drag as core_mouse_drag
from ._cli import as_cli


@as_cli()
async def mouse_drag(tab, start_x: int, start_y: int, end_x: int, end_y: int) -> dict:
    """Drag mouse from one point to another.

    Args:
        tab: Browser tab
        start_x: Start X coordinate
        start_y: Start Y coordinate
        end_x: End X coordinate
        end_y: End Y coordinate
    """
    try:
        await core_mouse_drag(tab, from_x=start_x, from_y=start_y, to_x=end_x, to_y=end_y)
        return {
            "dragged": True,
            "from": {"x": start_x, "y": start_y},
            "to": {"x": end_x, "y": end_y},
        }
    except Exception as e:
        return {"error": f"Mouse drag failed: {e}"}


if __name__ == "__main__":
    mouse_drag.cli_main()
