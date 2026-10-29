"""Window operations."""

from typing import Literal

from ai_dev_browser.cdp import emulation as cdp_emulation

from ._tab import Tab
from .config import DEFAULT_VIEWPORT_HEIGHT, DEFAULT_VIEWPORT_WIDTH, resolve_viewport


async def window_set(
    tab: Tab,
    width: int | None = None,
    height: int | None = None,
    state: Literal["normal", "maximized", "minimized", "fullscreen"] | None = None,
    focus: bool = False,
) -> dict:
    """Use when: you need the page to render at a specific width — to force a
    desktop (or a narrow, mobile) responsive layout — or to set the OS window's
    state / focus. To activate a hidden extension page, use
    window_set(state="normal", focus=True); its return already reports whether
    the selected page became visible and ready for input.

    `width`/`height` set the **render viewport** (`window.innerWidth`, what the
    page actually lays out against) — not the OS window frame. That is the size
    responsive apps read to choose desktop vs mobile layout, and it works
    headless and on a small display where the OS window can't grow. Tabs open at
    a desktop viewport by default (1600x950); use this to override, e.g. to
    reproduce a narrow-breakpoint / mobile layout. **The override persists** —
    an explicit `window_set` (even a narrow, sub-desktop one) is re-asserted on
    every subsequent tool call, so `window_set(width=390)` then `js_evaluate`
    sees 390 and width media queries fire, instead of the default snapping back.
    (Process-wide alternative: `AI_DEV_BROWSER_VIEWPORT=WxH`.)

    `state` and `focus` act on the selected page's window. In extension mode
    they use Chrome's window APIs; update/reload the bundled extension if its
    loaded version lacks support. Returns observed `state`, `focused`,
    `visibility`, and `input_ready` for window operations. A focused window can
    still have a hidden page (for example under native occlusion). When
    `input_ready` is false, show the actual selected tab/window and inspect it
    before input; focus emulation does not resolve this condition.
    `focused` is document focus; `tab_active` and `window_focused` are separate
    Chrome observations (null when unavailable). An active tab in a focused,
    normal window can still be hidden. These APIs do not identify native
    occlusion, another desktop or a locked session as the specific cause.

    Args:
        tab: Tab instance
        width: Render viewport width in pixels (innerWidth)
        height: Render viewport height in pixels (innerHeight)
        state: OS window state — "normal", "maximized", "minimized", or
            "fullscreen" (headed only)
        focus: If True, request activation and report observed document focus
            and visibility; cannot be combined with state="minimized"

    Returns:
        dict with viewport settings and observed window/page state. `success`
        reports whether requested state/focus was observed; `input_ready`
        reports genuine page visibility independently of document focus.

    Failure:
        Pass at least one of `width` / `height` / `state` / `focus`. `state`
        and `focus` request window operations; inspect returned visibility
        before input. A hidden page needs its actual Chrome tab/window shown.
        Unknown/mismatched extension versions require an ordinary extension
        update/reload; this can reset control, so inspect ownership again.
        `focused` is document focus: inspect `tab_active` and `window_focused`
        separately. If both are true but visibility stays hidden, ask the human
        to show/uncover the selected window on their current unlocked desktop.
        These APIs cannot identify the specific native cause.
        Do not spoof visibility, replay completed input, or change transports
        to bypass a refusal. For layout use `width`/`height`.

    Example:
        window_set(width=1280, height=720)   # narrower viewport
        window_set(width=390, height=844)    # emulate a phone-width layout
        window_set(state="maximized")
        window_set(focus=True)
    """
    if state is not None and state not in {
        "normal",
        "maximized",
        "minimized",
        "fullscreen",
    }:
        raise ValueError("state must be normal, maximized, minimized, or fullscreen")
    if state == "minimized" and focus:
        raise ValueError(
            "Cannot focus a minimized window; restore it with state=normal"
        )
    result: dict[str, object] = {}

    if width is not None or height is not None:
        vp = resolve_viewport() or (DEFAULT_VIEWPORT_WIDTH, DEFAULT_VIEWPORT_HEIGHT)
        w = width if width is not None else vp[0]
        h = height if height is not None else vp[1]
        await tab.set_viewport(w, h)
        result.update({"width": w, "height": h})
        # Persist the explicit viewport so get_active_tab re-asserts THIS size
        # every call instead of forcing the desktop default back — otherwise a
        # narrow/mobile viewport (below the desktop threshold) is clobbered on
        # the next tool call. Best-effort; needs the launching port.
        from . import registry

        port = getattr(getattr(tab, "_browser", None), "port", None)
        if port is not None:
            registry.update_viewport(port, [int(w), int(h)])

    if state is not None:
        if state == "maximized":
            await tab.maximize()
        elif state == "minimized":
            await tab.minimize()
        elif state == "fullscreen":
            await tab.fullscreen()
        else:
            await tab.medimize()

    if focus:
        await tab.bring_to_front()

    if state is not None or focus:
        observed = (
            await tab._wait_input_visibility() if focus else await tab._input_state()
        )
        observation = await tab._input_observation(observed)
        actual_state = observation.get("window_state")
        ready = observed["visibility"] == "visible"
        focus_observed = observation.get("window_focused")
        if focus_observed is None:
            focus_observed = observed["focused"]
        result.update(
            state=actual_state,
            **observation,
            input_ready=ready,
            success=(state is None or actual_state == state)
            and (not focus or (ready and focus_observed)),
        )
        if not result["success"]:
            result.update(error_code="unsupported", retryable=False)

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

    Use window_set(state="normal", focus=True) to request actual window
    activation. Emulated focus is not evidence of physical window visibility
    and must not be used to bypass InputUnavailableError.

    Args:
        tab: Tab instance
        enabled: True to enable (default), False to disable

    Returns:
        dict with enabled status

    Failure:
        Confirm that this transport supports focus emulation via cdp_send.
        Emulated document focus does not create an OS window or make a remote
        browser visible to the user.
    """
    await tab.send(cdp_emulation.set_focus_emulation_enabled(enabled=enabled))
    # Keep the generator's default result_key ("success") — deliberately NOT
    # "enabled". `enabled=False` is a valid outcome, and a result_key of
    # "enabled" would make the wrapper read `False` as failure and inject a
    # failure hint. Do not add a TOOL_META override for this tool.
    return {"enabled": enabled}
