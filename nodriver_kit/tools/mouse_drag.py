"""Drag mouse from one point to another.

CLI:
    python -m nodriver_kit.tools.mouse_drag --start-x 100 --start-y 100 --end-x 200 --end-y 200

Python:
    from nodriver_kit.tools import mouse_drag
    result = await mouse_drag(tab, start_x=100, start_y=100, end_x=200, end_y=200)
"""

from nodriver_kit.core import mouse_drag as core_mouse_drag
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

    Returns:
        {"dragged": True, ...} on success
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
