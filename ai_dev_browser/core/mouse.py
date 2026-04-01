"""Mouse operations.

When a screenshot path is provided, coordinates are automatically scaled
from screenshot space to CSS viewport space using metadata embedded in
the PNG. This makes screenshot coordinates directly usable for clicking
without manual conversion.
"""

from ._tab import Tab

from . import human


def _scale_coords(x: float, y: float, screenshot: str | None) -> tuple[float, float]:
    """Scale coordinates from screenshot space to CSS viewport space."""
    if not screenshot:
        return x, y
    from .page import read_screenshot_metadata

    meta = read_screenshot_metadata(screenshot)
    factor = meta.get("scale_factor", 1.0)
    if factor != 1.0:
        return x * factor, y * factor
    return x, y


async def mouse_move(
    tab: Tab,
    x: float,
    y: float,
    screenshot: str | None = None,
    steps: int = 10,
    human_like: bool = None,
) -> bool:
    """Move mouse to coordinates.

    Args:
        tab: Tab instance
        x: X coordinate (in screenshot space if screenshot provided)
        y: Y coordinate (in screenshot space if screenshot provided)
        screenshot: Path to screenshot PNG. Coordinates are auto-scaled
                    from screenshot space to CSS viewport space.
        steps: Number of steps for smooth movement (native mode)
        human_like: Use gaussian path (default: from config)

    Returns:
        True on success
    """
    x, y = _scale_coords(x, y, screenshot)

    use_human = (
        human_like if human_like is not None else human.get_config().use_gaussian_path
    )

    if use_human:
        await human.mouse_move(tab, x, y, use_gaussian=True)
    else:
        await tab.mouse_move(x, y, steps=steps)
        human.set_last_mouse_pos(tab, x, y)
    return True


async def mouse_click(
    tab: Tab,
    x: float,
    y: float,
    screenshot: str | None = None,
    button: str = "left",
    double: bool = False,
    human_like: bool = None,
) -> bool:
    """Click at coordinates.

    Args:
        tab: Tab instance
        x: X coordinate (in screenshot space if screenshot provided)
        y: Y coordinate (in screenshot space if screenshot provided)
        screenshot: Path to screenshot PNG. Coordinates are auto-scaled
                    from screenshot space to CSS viewport space.
        button: "left", "right", or "middle"
        double: If True, double click
        human_like: Use human-like timing (default: from config)

    Returns:
        True on success
    """
    x, y = _scale_coords(x, y, screenshot)

    config = human.get_config()
    use_human = (
        human_like
        if human_like is not None
        else (config.use_gaussian_path or config.click_hold_enabled)
    )

    if use_human:
        if double:
            await human.mouse_double_click(tab, x, y, button=button)
        else:
            await human.mouse_click(tab, x, y, button=button)
    else:
        await tab.mouse_move(x, y, steps=1)
        await tab.mouse_click(x, y, button=button)
        if double:
            await tab.mouse_click(x, y, button=button)
        human.set_last_mouse_pos(tab, x, y)
    return True


async def mouse_drag(
    tab: Tab,
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    screenshot: str | None = None,
    steps: int = 10,
) -> bool:
    """Drag from one point to another.

    Args:
        tab: Tab instance
        from_x: Start X (in screenshot space if screenshot provided)
        from_y: Start Y (in screenshot space if screenshot provided)
        to_x: End X (in screenshot space if screenshot provided)
        to_y: End Y (in screenshot space if screenshot provided)
        screenshot: Path to screenshot PNG. Coordinates are auto-scaled.
        steps: Number of steps for smooth drag

    Returns:
        True on success
    """
    from_x, from_y = _scale_coords(from_x, from_y, screenshot)
    to_x, to_y = _scale_coords(to_x, to_y, screenshot)

    await tab.mouse_drag((from_x, from_y), (to_x, to_y), steps=steps)
    human.set_last_mouse_pos(tab, to_x, to_y)
    return True
