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
    """Use when: you need the cursor at specific coordinates without
    clicking — hover effects that need dwell, or positioning before a
    planned click/drag. Usually not needed standalone; prefer
    `hover_by_ref` (element-level) or `mouse_click` (one-shot).

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
    modifiers: int = 0,
    double: bool = False,
    human_like: bool = None,
) -> bool:
    """Use when: you need to click at raw screen coordinates — reading
    them off a `page_screenshot` (pass the same `screenshot` path here
    and coords auto-scale), or clicking on canvas / SVG / custom-rendered
    UI that has no DOM element to locate. For DOM elements, prefer the
    `click_by_*` tools — they're atomic and return navigation feedback.

    Args:
        tab: Tab instance
        x: X coordinate (in screenshot space if screenshot provided)
        y: Y coordinate (in screenshot space if screenshot provided)
        screenshot: Path to screenshot PNG. Coordinates are auto-scaled
                    from screenshot space to CSS viewport space.
        button: "left", "right", or "middle"
        modifiers: Modifier keys bitmask (1=Alt, 2=Ctrl, 4=Meta, 8=Shift)
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
        await tab.mouse_click(x, y, button=button, modifiers=modifiers)
        if double:
            await tab.mouse_click(x, y, button=button, modifiers=modifiers)
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
    """Use when: you're drawing on a canvas, resizing via a handle, or
    manipulating a custom UI with no draggable DOM element. For a
    specific element drag (reorder, drop on target), prefer `drag_by_ref`
    — it doesn't need coordinates.

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
