"""Window operations."""

import nodriver
import nodriver.cdp.emulation as cdp_emulation


async def resize_window(
    tab: nodriver.Tab,
    width: int = 1280,
    height: int = 720,
    left: int = 0,
    top: int = 0,
) -> None:
    """Resize browser window.

    Args:
        tab: Tab instance
        width: Window width
        height: Window height
        left: Window left position
        top: Window top position
    """
    await tab.set_window_size(left=left, top=top, width=width, height=height)


async def set_window_state(
    tab: nodriver.Tab,
    state: str = "normal",
) -> None:
    """Set window state.

    Args:
        tab: Tab instance
        state: "normal", "maximized", "minimized", or "fullscreen"
    """
    if state == "maximized":
        await tab.maximize()
    elif state == "minimized":
        await tab.minimize()
    elif state == "fullscreen":
        await tab.fullscreen()
    else:
        await tab.medimize()


async def set_focus_emulation(
    tab: nodriver.Tab,
    enabled: bool = True,
) -> None:
    """Enable or disable focus emulation.

    When enabled, the browser behaves as if it has focus even when the
    window is in the background. This is critical for sites like iCloud
    that require window focus to render confirmation dialogs, menus, and modals.

    Args:
        tab: Tab instance
        enabled: True to enable (default), False to disable
    """
    await tab.send(cdp_emulation.set_focus_emulation_enabled(enabled=enabled))
