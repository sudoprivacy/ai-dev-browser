"""Window operations."""

import nodriver


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
