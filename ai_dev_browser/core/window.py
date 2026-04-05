"""Window operations."""

from ai_dev_browser.cdp import emulation as cdp_emulation

from ._tab import Tab


async def window_set(
    tab: Tab,
    width: int | None = None,
    height: int | None = None,
    left: int | None = None,
    top: int | None = None,
    state: str | None = None,
    focus: bool = False,
) -> dict:
    """Set window size, position, state, and/or focus.

    Args:
        tab: Tab instance
        width: Window width (pixels)
        height: Window height (pixels)
        left: Window left position (pixels)
        top: Window top position (pixels)
        state: "normal", "maximized", "minimized", or "fullscreen"
        focus: If True, bring window to front

    Returns:
        dict with applied settings

    Example:
        window_set(width=1280, height=720)
        window_set(state="maximized")
        window_set(focus=True)
        window_set(width=800, height=600, state="normal", focus=True)
    """
    result: dict[str, object] = {}

    if width is not None or height is not None:
        await tab.set_window_size(
            left=left or 0,
            top=top or 0,
            width=width or 1280,
            height=height or 720,
        )
        result.update({"width": width, "height": height, "left": left, "top": top})

    if state is not None:
        if state == "maximized":
            await tab.maximize()
        elif state == "minimized":
            await tab.minimize()
        elif state == "fullscreen":
            await tab.fullscreen()
        else:
            await tab.medimize()
        result["state"] = state

    if focus:
        await tab.bring_to_front()
        result["focused"] = True

    return result or {"error": "No action specified"}


async def page_emulate_focus(
    tab: Tab,
    enabled: bool = True,
) -> dict:
    """Enable or disable focus emulation.

    When enabled, the browser behaves as if it has focus even when the
    window is in the background. Critical for sites that require window
    focus to render dialogs, menus, and modals.

    Args:
        tab: Tab instance
        enabled: True to enable (default), False to disable

    Returns:
        dict with enabled status
    """
    await tab.send(cdp_emulation.set_focus_emulation_enabled(enabled=enabled))
    return {"enabled": enabled}
