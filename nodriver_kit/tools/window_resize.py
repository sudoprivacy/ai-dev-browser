"""Resize browser window.

CLI:
    python -m nodriver_kit.tools.window_resize --width 1920 --height 1080

Python:
    from nodriver_kit.tools import window_resize
    result = await window_resize(tab, width=1920, height=1080)
"""

from nodriver_kit.core import resize_window
from ._cli import as_cli


@as_cli()
async def window_resize(tab, width: int, height: int) -> dict:
    """Resize the browser window.

    Args:
        tab: Browser tab
        width: Window width
        height: Window height

    Returns:
        {"resized": True, "width": ..., "height": ...}
    """
    try:
        await resize_window(tab, width=width, height=height)
        return {"resized": True, "width": width, "height": height}
    except Exception as e:
        return {"error": f"Resize window failed: {e}"}


if __name__ == "__main__":
    window_resize.cli_main()
