"""Window operations."""

import nodriver
import nodriver.cdp.emulation as cdp_emulation


async def resize_window(
    tab: nodriver.Tab,
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


async def set_window_state(
    tab: nodriver.Tab,
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


async def set_focus_emulation(
    tab: nodriver.Tab,
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


async def focus_window(tab: nodriver.Tab) -> dict:
    """Bring the browser window to front.

    Args:
        tab: Tab instance

    Returns:
        dict with focused status
    """
    await tab.bring_to_front()
    return {"focused": True}
