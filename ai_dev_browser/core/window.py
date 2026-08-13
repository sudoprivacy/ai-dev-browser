"""Window operations."""

from ai_dev_browser.cdp import emulation as cdp_emulation

from ._tab import Tab
from .config import DEFAULT_VIEWPORT_HEIGHT, DEFAULT_VIEWPORT_WIDTH, resolve_viewport


async def window_set(
    tab: Tab,
    width: int | None = None,
    height: int | None = None,
    state: str | None = None,
    focus: bool = False,
) -> dict:
    """Use when: you need the page to render at a specific width — to force a
    desktop (or a narrow, mobile) responsive layout — or to set the OS window's
    state / focus.

    `width`/`height` set the **render viewport** (`window.innerWidth`, what the
    page actually lays out against) — not the OS window frame. That is the size
    responsive apps read to choose desktop vs mobile layout, and it works
    headless and on a small display where the OS window can't grow. Tabs
    already open at a desktop viewport by default (1600x950); use this to
    override, e.g. to reproduce a narrow-breakpoint layout. A narrower-than-
    desktop override lasts for the current session but is re-asserted to the
    default on the next tool call (a tab is never left mobile-width); for a
    viewport that sticks everywhere, set `AI_DEV_BROWSER_VIEWPORT=WxH`.

    `state` and `focus` act on the OS window (headed Chrome only).

    Args:
        tab: Tab instance
        width: Render viewport width in pixels (innerWidth)
        height: Render viewport height in pixels (innerHeight)
        state: OS window state — "normal", "maximized", "minimized", or
            "fullscreen" (headed only)
        focus: If True, bring the OS window to front (headed only)

    Returns:
        dict with applied settings

    Failure:
        Pass at least one of `width` / `height` / `state` / `focus`. `state`
        and `focus` drive the OS window and need headed Chrome (they no-op or
        error headless); for layout use `width`/`height` (the render viewport),
        which works headless.

    Example:
        window_set(width=1280, height=720)   # narrower viewport
        window_set(width=390, height=844)    # emulate a phone-width layout
        window_set(state="maximized")
        window_set(focus=True)
    """
    result: dict[str, object] = {}

    if width is not None or height is not None:
        vp = resolve_viewport() or (DEFAULT_VIEWPORT_WIDTH, DEFAULT_VIEWPORT_HEIGHT)
        w = width if width is not None else vp[0]
        h = height if height is not None else vp[1]
        await tab.set_viewport(w, h)
        result.update({"width": w, "height": h})

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

    if not result:
        raise ValueError(
            "window_set needs at least one of width, height, state, or focus"
        )
    return result


async def page_emulate_focus(
    tab: Tab,
    enabled: bool = True,
) -> dict:
    """Use when: a site only renders dialogs / menus / modals while its window
    has focus, but automation drives it in the background (headless, or behind
    other windows) so they never appear. Enabling makes the browser behave as
    if focused regardless of real window focus.

    Args:
        tab: Tab instance
        enabled: True to enable (default), False to disable

    Returns:
        dict with enabled status
    """
    await tab.send(cdp_emulation.set_focus_emulation_enabled(enabled=enabled))
    # Keep the generator's default result_key ("success") — deliberately NOT
    # "enabled". `enabled=False` is a valid outcome, and a result_key of
    # "enabled" would make the wrapper read `False` as failure and inject a
    # failure hint. Do not add a TOOL_META override for this tool.
    return {"enabled": enabled}
