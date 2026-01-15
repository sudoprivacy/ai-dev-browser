"""Mouse operations."""

import nodriver


async def mouse_move(
    tab: nodriver.Tab,
    x: float,
    y: float,
    steps: int = 10,
) -> None:
    """Move mouse to coordinates.

    Args:
        tab: Tab instance
        x: X coordinate
        y: Y coordinate
        steps: Number of steps for smooth movement
    """
    await tab.mouse_move(x, y, steps=steps)


async def mouse_click(
    tab: nodriver.Tab,
    x: float,
    y: float,
    button: str = "left",
    double: bool = False,
) -> None:
    """Click at coordinates.

    Args:
        tab: Tab instance
        x: X coordinate
        y: Y coordinate
        button: "left", "right", or "middle"
        double: If True, double click
    """
    await tab.mouse_move(x, y)
    await tab.mouse_click(x, y, button=button)
    if double:
        await tab.mouse_click(x, y, button=button)


async def mouse_drag(
    tab: nodriver.Tab,
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    steps: int = 10,
) -> None:
    """Drag from one point to another.

    Args:
        tab: Tab instance
        from_x: Start X coordinate
        from_y: Start Y coordinate
        to_x: End X coordinate
        to_y: End Y coordinate
        steps: Number of steps for smooth drag
    """
    await tab.mouse_drag((from_x, from_y), (to_x, to_y), steps=steps)
