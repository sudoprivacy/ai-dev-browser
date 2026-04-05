"""Window operations."""

from ai_dev_browser.cdp import emulation as cdp_emulation

from ._tab import Tab


async def window_resize(
    tab: Tab,
    width: int = 1280,
    height: int = 720,
    left: int = 0,
    top: int = 0,
) -> dict:
    """Resize browser window.

    Args:
        tab: Tab instance
        width: Window width
        height: Window height
        left: Window left position
        top: Window top position

    Returns:
        dict with width, height, left, top
    """
    await tab.set_window_size(left=left, top=top, width=width, height=height)
    return {"width": width, "height": height, "left": left, "top": top}


async def window_state(
    tab: Tab,
    state: str = "normal",
) -> dict:
    """Set window state.

    Args:
        tab: Tab instance
        state: "normal", "maximized", "minimized", or "fullscreen"

    Returns:
        dict with state
    """
    if state == "maximized":
        await tab.maximize()
    elif state == "minimized":
        await tab.minimize()
    elif state == "fullscreen":
        await tab.fullscreen()
    else:
        await tab.medimize()
    return {"state": state}


async def window_focus_emulation(
    tab: Tab,
    enabled: bool = True,
) -> dict:
    """Enable or disable focus emulation.

    When enabled, the browser behaves as if it has focus even when the
    window is in the background. This is critical for sites like iCloud
    that require window focus to render confirmation dialogs, menus, and modals.

    Args:
        tab: Tab instance
        enabled: True to enable (default), False to disable

    Returns:
        dict with enabled status
    """
    await tab.send(cdp_emulation.set_focus_emulation_enabled(enabled=enabled))
    return {"enabled": enabled}


async def window_focus(tab: Tab) -> dict:
    """Bring the browser window to front.

    Args:
        tab: Tab instance

    Returns:
        dict with focused status
    """
    await tab.bring_to_front()
    return {"focused": True}
