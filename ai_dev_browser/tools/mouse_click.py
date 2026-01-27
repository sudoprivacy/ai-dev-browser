"""Click at coordinates."""

from ai_dev_browser.core import mouse_click as core_mouse_click
from ._cli import as_cli


@as_cli()
async def mouse_click(tab, x: int, y: int, button: str = "left") -> dict:
    """Click at coordinates.

    Args:
        tab: Browser tab
        x: X coordinate
        y: Y coordinate
        button: Mouse button ("left", "right", "middle")
    """
    try:
        await core_mouse_click(tab, x=x, y=y, button=button)
        return {"clicked": True, "x": x, "y": y, "button": button}
    except Exception as e:
        return {"error": f"Mouse click failed: {e}"}


if __name__ == "__main__":
    mouse_click.cli_main()
