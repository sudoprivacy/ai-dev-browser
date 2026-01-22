"""Click at coordinates.

CLI:
    python -m ai_dev_browser.tools.mouse_click --x 100 --y 200
    python -m ai_dev_browser.tools.mouse_click --x 100 --y 200 --button right

Python:
    from ai_dev_browser.tools import mouse_click
    result = await mouse_click(tab, x=100, y=200)
"""

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

    Returns:
        {"clicked": True, "x": ..., "y": ...} on success
    """
    try:
        await core_mouse_click(tab, x=x, y=y, button=button)
        return {"clicked": True, "x": x, "y": y, "button": button}
    except Exception as e:
        return {"error": f"Mouse click failed: {e}"}


if __name__ == "__main__":
    mouse_click.cli_main()
