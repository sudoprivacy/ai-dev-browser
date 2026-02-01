"""Mouse operations."""

import nodriver

from . import human


async def mouse_move(
    tab: nodriver.Tab,
    x: float,
    y: float,
    steps: int = 10,
    human_like: bool = None,
) -> bool:
    """Move mouse to coordinates.

    Args:
        tab: Tab instance
        x: X coordinate
        y: Y coordinate
        steps: Number of steps for smooth movement (native mode)
        human_like: Use gaussian path (default: from config)

    Returns:
        True on success
    """
    use_human = human_like if human_like is not None else human.get_config().use_gaussian_path

    if use_human:
        await human.mouse_move(tab, x, y, use_gaussian=True)
    else:
        await tab.mouse_move(x, y, steps=steps)
        # Track position for human module
        human.set_last_mouse_pos(tab, x, y)
    return True


async def mouse_click(
    tab: nodriver.Tab,
    x: float,
    y: float,
    button: str = "left",
    double: bool = False,
    human_like: bool = None,
) -> bool:
    """Click at coordinates.

    Args:
        tab: Tab instance
        x: X coordinate
        y: Y coordinate
        button: "left", "right", or "middle"
        double: If True, double click
        human_like: Use human-like timing (default: from config)

    Returns:
        True on success
    """
    # Check if any human-like features are enabled
    config = human.get_config()
    use_human = human_like if human_like is not None else (
        config.use_gaussian_path or config.click_hold_enabled
    )

    if use_human:
        if double:
            await human.mouse_double_click(tab, x, y, button=button)
        else:
            await human.mouse_click(tab, x, y, button=button)
    else:
        await tab.mouse_move(x, y)
        await tab.mouse_click(x, y, button=button)
        if double:
            await tab.mouse_click(x, y, button=button)
        human.set_last_mouse_pos(tab, x, y)
    return True


async def mouse_drag(
    tab: nodriver.Tab,
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    steps: int = 10,
) -> bool:
    """Drag from one point to another.

    Args:
        tab: Tab instance
        from_x: Start X coordinate
        from_y: Start Y coordinate
        to_x: End X coordinate
        to_y: End Y coordinate
        steps: Number of steps for smooth drag

    Returns:
        True on success
    """
    await tab.mouse_drag((from_x, from_y), (to_x, to_y), steps=steps)
    human.set_last_mouse_pos(tab, to_x, to_y)
    return True
