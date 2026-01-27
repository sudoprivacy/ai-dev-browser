"""Resize browser window."""

from ai_dev_browser.core import resize_window
from ._cli import as_cli


@as_cli()
async def window_resize(tab, width: int, height: int) -> dict:
    """Resize the browser window.

    Args:
        tab: Browser tab
        width: Window width
        height: Window height
    """
    try:
        await resize_window(tab, width=width, height=height)
        return {"resized": True, "width": width, "height": height}
    except Exception as e:
        return {"error": f"Resize window failed: {e}"}


if __name__ == "__main__":
    window_resize.cli_main()
