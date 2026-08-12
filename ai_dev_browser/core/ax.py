"""Accessibility tree operations for element interaction."""

import asyncio

from ai_dev_browser.cdp import dom
from ai_dev_browser.cdp import input_ as cdp_input
from ai_dev_browser.cdp import page

from . import human
from ._element import Element
from ._ref import node_id_of, parse_ref
from ._tab import Tab

from .snapshot import _get_snapshot


async def get_element_by_ref(tab: Tab, ref: str) -> Element:
    """Resolve a `ref` from `page_discover` into a DOM Element.

    The bridge between the two ways this library names an element: the
    accessibility tree's `ref` and the DOM's `Element`. It belongs in the ref
    layer, not the DOM layer — it used to live in `_element.py`, which put
    knowledge of an AX-tree naming scheme at the bottom of the DOM stack and
    re-implemented the ref grammar to do it. The grammar now lives once, in
    `_ref.py`.

    Args:
        tab: Tab instance
        ref: Element ref from page_discover (e.g., "5#214" or "FRAME_ABC:5#214")

    Returns:
        Element instance

    Raises:
        ValueError: If ref carries no node_id, or the node is gone.
    """
    _, _, node_id = parse_ref(ref)
    if node_id is None:
        raise ValueError(f"Invalid ref format (no node_id): {ref}")

    try:
        node_info = await tab.send(
            dom.describe_node(backend_node_id=dom.BackendNodeId(node_id), depth=0)
        )
    except Exception as e:
        raise ValueError(f"Element not found for ref {ref}: {e}") from e

    return Element(node_info, tab)


async def _get_frame_id_by_prefix(tab: Tab, prefix: str) -> str | None:
    """Find full frame ID by prefix (e.g., 'FRAME_ABC123' -> full frame ID)."""
    try:
        result = await tab.send(page.get_frame_tree())

        def find_frame(frame_tree):
            frame = frame_tree.frame
            if f"FRAME_{frame.id_[:8]}" == prefix:
                return frame.id_
            if frame_tree.child_frames:
                for child in frame_tree.child_frames:
                    found = find_frame(child)
                    if found:
                        return found
            return None

        return find_frame(result)
    except Exception:
        return None


async def _click_by_node_id(
    tab: Tab,
    node_id: int,
    human_like: bool = True,
) -> dict:
    """Click element by backend node ID via CDP.

    Args:
        tab: Tab instance
        node_id: Backend DOM node ID
        human_like: Route through the shared human-like actuator (gaussian
            approach path + in-bounds random offset). Same default and same
            meaning as `click_by_text`'s `human_like` — an element is named
            differently by each `*_by_*` tool, but clicked the same way.

    Returns:
        dict with clicked status
    """
    try:
        # Wrap int in BackendNodeId
        backend_node_id = dom.BackendNodeId(node_id)

        # Get box model for the node
        box = await tab.send(dom.get_box_model(backend_node_id=backend_node_id))
        if not box or not box.content:
            return {"clicked": False, "error": "Could not get element box model"}

        # Get center of content box (content quad has 8 values: 4 x,y pairs)
        quad = box.content
        x = (quad[0] + quad[2] + quad[4] + quad[6]) / 4
        y = (quad[1] + quad[3] + quad[5] + quad[7]) / 4

        if human_like:
            await human.click_box(tab, (x, y), box.width, box.height)
        else:
            await tab.send(
                cdp_input.dispatch_mouse_event(
                    type_="mousePressed",
                    x=x,
                    y=y,
                    button=cdp_input.MouseButton.LEFT,
                    click_count=1,
                )
            )
            await tab.send(
                cdp_input.dispatch_mouse_event(
                    type_="mouseReleased",
                    x=x,
                    y=y,
                    button=cdp_input.MouseButton.LEFT,
                    click_count=1,
                )
            )
        return {"clicked": True, "node_id": node_id}
    except Exception as e:
        return {"clicked": False, "error": str(e)}


async def _wait_for_ax_element(
    tab: Tab,
    wait_for_role: str | None = None,
    wait_for_name: str | None = None,
    timeout: float = 5.0,
    interval: float = 0.3,
) -> dict:
    """Wait for an element to appear in the accessibility tree.

    Args:
        tab: Tab instance
        wait_for_role: Role to wait for (e.g., "button", "menu")
        wait_for_name: Name to wait for (substring match)
        timeout: Max wait time in seconds
        interval: Poll interval in seconds

    Returns:
        dict with found status and element info
    """
    if not wait_for_role and not wait_for_name:
        return {"found": True, "skipped": True}

    elapsed = 0.0
    while elapsed < timeout:
        await asyncio.sleep(interval)
        elapsed += interval

        try:
            elements = await _get_snapshot(tab)
            for el in elements:
                role_match = wait_for_role is None or el.get("role") == wait_for_role
                name_match = wait_for_name is None or wait_for_name in el.get(
                    "name", ""
                )
                if role_match and name_match:
                    return {
                        "found": True,
                        "element": {
                            "role": el.get("role"),
                            "name": el.get("name"),
                            "ref": el.get("ref"),
                        },
                    }
        except Exception:
            pass  # Keep trying

    return {"found": False, "timeout": True}


async def _click_ax_element(
    tab: Tab,
    ref: str | None = None,
    node_id: int | None = None,
    wait_for_role: str | None = None,
    wait_for_name: str | None = None,
    wait_timeout: float = 5.0,
    wait_interval: float = 0.3,
    human_like: bool = True,
) -> dict:
    """Click element by accessibility tree ref or node_id.

    Use ax_tree (get_accessibility_tree) to get element refs, then this function
    to click them. For stable clicks, pass node_id directly.

    Supports iframe elements with prefixed refs like "FRAME_ABC123:5".

    Args:
        tab: Tab instance
        ref: Element ref from ax_tree (e.g., "5" or "FRAME_ABC123:5" or "5#214")
        node_id: Backend node ID - direct click, no re-fetch needed
        wait_for_role: After click, wait for element with this role
        wait_for_name: After click, wait for element with this name
        wait_timeout: Max time to wait in seconds
        wait_interval: Poll interval in seconds

    Returns:
        dict with clicked status, element info, and optional wait result
    """
    # Must specify at least one of ref or node_id
    if ref is None and node_id is None:
        return {"error": "Must specify ref or node_id"}

    # If node_id provided directly, use it (stable, no re-fetch)
    if node_id is not None:
        result = await _click_by_node_id(tab, node_id, human_like=human_like)
        if result.get("clicked") and (wait_for_role or wait_for_name):
            waited = await _wait_for_ax_element(
                tab, wait_for_role, wait_for_name, wait_timeout, wait_interval
            )
            if waited.get("found") and not waited.get("skipped"):
                result["waited_for"] = waited.get("element")
            elif waited.get("timeout"):
                result["wait_timeout"] = True
        return result

    # Parse ref to extract frame prefix, local ref, and embedded node_id
    frame_prefix, local_ref, embedded_node_id = parse_ref(ref)

    # If ref contains embedded node_id, use it directly (most reliable)
    if embedded_node_id is not None:
        result = await _click_by_node_id(tab, embedded_node_id, human_like=human_like)
        if result.get("clicked"):
            result["ref"] = ref
            if wait_for_role or wait_for_name:
                waited = await _wait_for_ax_element(
                    tab, wait_for_role, wait_for_name, wait_timeout, wait_interval
                )
                if waited.get("found") and not waited.get("skipped"):
                    result["waited_for"] = waited.get("element")
                elif waited.get("timeout"):
                    result["wait_timeout"] = True
        return result

    # Fallback: re-fetch snapshot and find by ref (less reliable)
    # Get frame ID if this is an iframe ref
    frame_id = None
    if frame_prefix:
        frame_id = await _get_frame_id_by_prefix(tab, frame_prefix)
        if not frame_id:
            return {"error": f"Frame '{frame_prefix}' not found"}

    # Get accessibility tree for the appropriate frame
    elements = await _get_snapshot(tab, frame_id=frame_id)

    # Find element by local ref (without frame prefix or node_id suffix).
    # The caller's ref may be a bare "9" while a freshly-taken snapshot mints
    # "9#214", so compare on the index part.
    target = None
    for el in elements:
        _, el_index, _ = parse_ref(el.get("ref", ""))
        if el_index == local_ref:
            target = el
            break

    if not target:
        return {"error": f"Element with ref '{ref}' not found"}

    target_node_id = node_id_of(target.get("ref", ""))
    if not target_node_id:
        return {"error": f"Element ref '{ref}' has no nodeId"}

    # Click the element
    result = await _click_by_node_id(tab, target_node_id, human_like=human_like)
    if result.get("clicked"):
        result["ref"] = ref
        result["element"] = {
            "role": target.get("role"),
            "name": target.get("name"),
        }
        if wait_for_role or wait_for_name:
            waited = await _wait_for_ax_element(
                tab, wait_for_role, wait_for_name, wait_timeout, wait_interval
            )
            if waited.get("found") and not waited.get("skipped"):
                result["waited_for"] = waited.get("element")
            elif waited.get("timeout"):
                result["wait_timeout"] = True

    return result


async def click_by_ref(
    tab: Tab,
    ref: str,
    human_like: bool = True,
) -> dict:
    """Use when: you already called `page_discover()` / `find_by_text`
    and have a ref (there was no natural id / xpath / text locator, or
    the target is inside an iframe that `click_by_text` can't reach).
    Atomic click + navigation feedback.

    Returns `{clicked, ref, role, name, url_before, url_after,
    title_after, navigated}` — **don't** screenshot after the click
    just to see if it worked, `navigated` + `url_after` already tell
    you. Only screenshot when you need to inspect visual state the
    return values can't express.

    If you know the element's html id / xpath / unique text, skip
    `page_discover` and go directly to `click_by_html_id` /
    `click_by_xpath` / `click_by_text` (one call vs two).

    Args:
        tab: Tab instance
        ref: Element ref from page_discover() (e.g., "5#214" or "FRAME_ABC123:5#214")
        human_like: Use the human-like actuator — gaussian approach path and a
            random in-bounds offset instead of a dead-centre click. Default
            True, same as `click_by_text`: how you *name* an element should not
            change how it gets *clicked*.

    Returns:
        dict with clicked status, element info, and navigation feedback:
        `{clicked, ref, role, name, url_before, url_after, title_after, navigated}`.
        `navigated=True` means the top-level URL changed after the click
        (SPA route change or full page load).

    Failure:
        Ref is stale (page navigated or element was removed between
        the `page_discover` / `find_by_text` call that returned it
        and this click). Re-run `page_discover` or `find_by_text` to
        get a fresh ref, or use a stable locator — `click_by_html_id`
        / `click_by_xpath` / `click_by_text`.

    Example:
        # First page_discover elements
        result = page_discover()
        # Then click by ref
        click_by_ref("5#214")
    """
    # Import lazily to avoid a circular dependency with elements.py, which
    # imports from this module.
    from .elements import _capture_page_state, _with_nav_feedback

    url_before_state = await _capture_page_state(tab)
    result = await _click_ax_element(tab, ref=ref, human_like=human_like)
    result["url_before"] = url_before_state.get("url", "")
    if not result.get("clicked"):
        result.update(
            {
                "navigated": False,
                "url_after": result["url_before"],
                "title_after": "",
            }
        )
        return result
    return await _with_nav_feedback(tab, result)


async def focus_by_ref(
    tab: Tab,
    ref: str,
) -> dict:
    """Use when: you want an input focused but NOT clicked (to avoid firing
    click handlers / dropdowns). Prereq: a `ref` from `page_discover()`.
    Returns `{focused, ref}` — follow with `type_by_ref` to enter text.

    Args:
        tab: Tab instance
        ref: Element ref from page_discover() (e.g., "5#214")

    Returns:
        dict with focused status

    Example:
        focus_by_ref("5#214")
    """
    # Parse ref to extract node_id
    _, _, node_id = parse_ref(ref)

    if node_id is None:
        return {"focused": False, "error": f"Invalid ref format: {ref}"}

    try:
        backend_node_id = dom.BackendNodeId(node_id)
        await tab.send(dom.focus(backend_node_id=backend_node_id))
        return {"focused": True, "ref": ref}
    except Exception as e:
        return {"focused": False, "error": str(e)}


# Keyboard keys — real CDP key events carrying the fields heavy / legacy
# frameworks actually read. `type_by_ref` types via `Input.insertText` (an
# IME-style commit): it lands text reliably but dispatches NO key events, so
# "press Enter to submit" has no path. A naive `Input.dispatchKeyEvent(Enter)`
# also commonly fails on ERP-grade UIs: they gate Enter on `event.keyCode === 13`
# (which only exists when `windowsVirtualKeyCode` is set) and some listen on
# `keypress` (which only fires when the key carries `text`). Each spec sets both
# plus the DOM `key`/`code`, so the event is indistinguishable from a real press.
#
#   name -> (dom key, dom code, virtual key code, text | None)
_KEY_SPECS: dict[str, tuple[str, str, int, str | None]] = {
    "enter": ("Enter", "Enter", 13, "\r"),
    "tab": ("Tab", "Tab", 9, None),
    "escape": ("Escape", "Escape", 27, None),
    "backspace": ("Backspace", "Backspace", 8, None),
    "delete": ("Delete", "Delete", 46, None),
    "space": (" ", "Space", 32, " "),
    "arrowup": ("ArrowUp", "ArrowUp", 38, None),
    "arrowdown": ("ArrowDown", "ArrowDown", 40, None),
    "arrowleft": ("ArrowLeft", "ArrowLeft", 37, None),
    "arrowright": ("ArrowRight", "ArrowRight", 39, None),
    "home": ("Home", "Home", 36, None),
    "end": ("End", "End", 35, None),
    "pageup": ("PageUp", "PageUp", 33, None),
    "pagedown": ("PageDown", "PageDown", 34, None),
}

# Aliases the LLM is likely to pass for the same key.
_KEY_ALIASES = {
    "esc": "escape",
    "del": "delete",
    "return": "enter",
    "up": "arrowup",
    "down": "arrowdown",
    "left": "arrowleft",
    "right": "arrowright",
}


def _resolve_key(name: str) -> tuple[str, str, int, str | None] | None:
    norm = name.strip().lower().replace("_", "").replace("-", "").replace(" ", "")
    norm = _KEY_ALIASES.get(norm, norm)
    return _KEY_SPECS.get(norm)


async def _dispatch_key(
    tab: Tab,
    dom_key: str,
    code: str,
    vkey: int,
    modifiers: int = 0,
    text: str | None = None,
) -> None:
    """The one key-dispatch path: send a real keyDown + keyUp via CDP.

    Both `press_key` and `type_by_ref`'s select-all/backspace clear route
    through here so the event shape can't drift between them — in particular
    `windowsVirtualKeyCode` is always set, so `event.keyCode` is populated
    (legacy frameworks gate on it). `text` on the keyDown is what makes Blink
    also fire `keypress` (and, in an editable, `beforeinput`/`input`); it is
    None for non-text keys and keyUp never carries it.
    """
    await tab.send(
        cdp_input.dispatch_key_event(
            "keyDown",
            key=dom_key,
            code=code,
            windows_virtual_key_code=vkey,
            native_virtual_key_code=vkey,
            modifiers=modifiers,
            text=text,
            unmodified_text=text,
        )
    )
    await tab.send(
        cdp_input.dispatch_key_event(
            "keyUp",
            key=dom_key,
            code=code,
            windows_virtual_key_code=vkey,
            native_virtual_key_code=vkey,
            modifiers=modifiers,
        )
    )


async def press_key(
    tab: Tab,
    key: str,
    ref: str | None = None,
    modifiers: int = 0,
) -> dict:
    """Use when: text is already in a field (via `type_by_ref` /
    `type_by_text`) and you need to *submit* or navigate with a real key —
    most often **Enter** to fire a search / form, or Tab / Escape / arrows.

    Sends a genuine CDP key event (isTrusted=true) to the focused element
    with the `keyCode` and `keypress` that heavy / legacy frameworks (ERP,
    jQuery-era widgets) require — a synthetic `KeyboardEvent`, or a bare
    `dispatchKeyEvent` without a virtual key code, does NOT trigger those.

    Pass `ref` to focus that element first (from `page_discover` /
    `find_by_*`); omit it to press on whatever is currently focused — e.g.
    right after `type_by_ref`, which leaves the field focused. For the common
    "type then Enter", prefer `type_by_ref(..., enter=True)` (one call).

    Returns once the key is dispatched, not when the app reacts — an Enter
    that kicks off a search resolves before the dropdown renders. Poll for
    the result with `page_wait_element` / `page_discover`, don't screenshot.

    Args:
        tab: Tab instance
        key: Key name — Enter, Tab, Escape, Backspace, Delete, Space,
            ArrowUp/Down/Left/Right, Home, End, PageUp, PageDown
            (case-insensitive; aliases: esc, del, return, up/down/left/right)
        ref: Optional element ref to focus before pressing
        modifiers: Modifier bitmask (Alt=1, Ctrl=2, Meta=4, Shift=8)

    Returns:
        dict `{pressed: True, key, ref}` on success, or
        `{pressed: False, reason}` for an unknown key / invalid ref.

    Failure:
        If a heavy framework still ignores Enter, confirm the field is
        focused — press with no `ref` right after `type_by_ref`, which leaves
        focus on it — and that the text actually landed. A stale `ref`:
        re-run `page_discover` / `find_by_*`. (An unknown key name comes back
        inline with the supported list.)
    """
    spec = _resolve_key(key)
    if spec is None:
        return {
            "pressed": False,
            "reason": f"unknown key {key!r}; supported: "
            + ", ".join(sorted(_KEY_SPECS)),
        }
    dom_key, code, vkey, text = spec

    if ref is not None:
        _, _, node_id = parse_ref(ref)
        if node_id is None:
            return {"pressed": False, "reason": f"invalid ref (no node id): {ref!r}"}
        try:
            await tab.send(dom.focus(backend_node_id=dom.BackendNodeId(node_id)))
        except Exception as e:
            return {"pressed": False, "reason": f"could not focus {ref!r}: {e}"}

    await _dispatch_key(tab, dom_key, code, vkey, modifiers=modifiers or 0, text=text)
    return {"pressed": True, "key": dom_key, "ref": ref}


async def type_by_ref(
    tab: Tab,
    ref: str,
    text: str,
    clear: bool = False,
    enter: bool = False,
) -> dict:
    """Use when: you have a `ref` from `page_discover()` and want to type
    into that specific input. Returns `{typed, ref, text}` (plus `entered`
    when `enter=True`).

    If you can identify the input by its visible label / placeholder, skip
    `page_discover` and use `type_by_text` directly.

    Set `enter=True` to press Enter after typing — the atomic "type into the
    search box and submit" for heavy JS UIs (ERP smart-search, etc.) where the
    dropdown only appears on a real Enter. For other submit keys use
    `press_key` separately.

    Args:
        tab: Tab instance
        ref: Element ref from page_discover() (e.g., "5#214")
        text: Text to type into the element
        clear: If True, clear existing content first
        enter: If True, press Enter after typing (submits the field)

    Returns:
        dict with typed status; includes `entered` when `enter=True`

    Example:
        type_by_ref("5#214", "myusername")
        type_by_ref("5#214", "newvalue", clear=True)
        type_by_ref("5#214", "widget", enter=True)   # type + submit
    """
    # First focus the element
    focus_result = await focus_by_ref(tab, ref)
    if not focus_result.get("focused"):
        return {"typed": False, "error": focus_result.get("error", "Focus failed")}

    # Clear if requested: select the field's content in JS, then delete it
    # with a real Backspace (so frameworks see a genuine delete event).
    # Selection is done via el.select() rather than a Ctrl/Cmd+A chord because
    # select-all is platform-specific — Ctrl+A is a caret move on macOS, so the
    # old key-based clear deleted only one char there ("OLDVALUE" -> "OLDVALU").
    if clear:
        try:
            element = await get_element_by_ref(tab, ref)
            await element.apply(
                "(el) => { if (el.focus) el.focus();"
                " if (typeof el.select === 'function') { el.select(); }"
                " else { const r = document.createRange();"
                " r.selectNodeContents(el); const s = window.getSelection();"
                " s.removeAllRanges(); s.addRange(r); } }"
            )
        except Exception:
            pass
        bs_key, bs_code, bs_vkey, _ = _KEY_SPECS["backspace"]
        await _dispatch_key(tab, bs_key, bs_code, bs_vkey)

    # Type text using insertText (most reliable for input fields)
    await tab.send(cdp_input.insert_text(text=text))

    result = {"typed": True, "ref": ref, "text": text}
    if enter:
        # Re-focus the same ref before Enter so the key lands on this field
        # even if insertText or a framework moved focus.
        pressed = await press_key(tab, "Enter", ref=ref)
        result["entered"] = bool(pressed.get("pressed"))
    return result


# ---------------------------------------------------------------------------
# Element tools (by ref) — all use get_element_by_ref helper
# ---------------------------------------------------------------------------


async def hover_by_ref(
    tab: Tab,
    ref: str,
) -> dict:
    """Use when: you need to trigger a hover-only UI (hover menus, tooltips,
    dropdown previews) without clicking. Prereq: `ref` from `page_discover()`.
    Returns `{hovered, ref}`. Typical next step: `page_discover` again to
    see the newly-revealed elements, or `click_by_text` on the hover-shown
    item.

    Args:
        tab: Tab instance
        ref: Element ref from page_discover()

    Returns:
        dict with hovered status
    """
    element = await get_element_by_ref(tab, ref)
    await element.mouse_move()
    return {"hovered": True, "ref": ref}


async def highlight_by_ref(
    tab: Tab,
    ref: str,
    duration: float = 2.0,
) -> dict:
    """Use when: you want visual confirmation that a `ref` resolves to the
    element you think it does (debugging / verifying before an action).
    Draws a colored overlay on the page for `duration` seconds. Returns
    `{highlighted, ref}`. Follow with `page_screenshot` to capture the
    overlay.

    Args:
        tab: Tab instance
        ref: Element ref from page_discover()
        duration: How long to show highlight in seconds

    Returns:
        dict with highlighted status
    """
    element = await get_element_by_ref(tab, ref)
    await element.highlight_overlay(duration=duration)
    return {"highlighted": True, "ref": ref}


async def html_by_ref(
    tab: Tab,
    ref: str,
) -> dict:
    """Use when: you have a `ref` and want just that element's outerHTML
    (smaller payload than `page_html`'s whole-document dump). Useful for
    inspecting attributes / nested structure that `page_discover`'s
    summary doesn't show. Prereq: `ref` from `page_discover()`.
    Returns `{html}`.

    Args:
        tab: Tab instance
        ref: Element ref from page_discover()

    Returns:
        dict with html content
    """
    element = await get_element_by_ref(tab, ref)
    html = await element.get_html()
    return {"html": html, "ref": ref}


async def screenshot_by_ref(
    tab: Tab,
    ref: str,
    path: str | None = None,
    image_cap: dict | None = None,
) -> dict:
    """Use when: you need just one element's pixels (not the whole page) —
    smaller file, tighter crop for LLM vision. Prereq: `ref` from
    `page_discover()`. Returns `{path, size, ref, width, height}`
    (plus `format` and `capped` when `image_cap` is provided).

    Args:
        tab: Tab instance
        ref: Element ref from page_discover()
        path: File path to save. When omitted, defaults to
              `$AI_DEV_BROWSER_OUTPUT_DIR/{timestamp}_element.png` if the env
              var is set, otherwise `./output/{timestamp}_element.png`
              relative to cwd — same resolution as `page_screenshot`.
        image_cap: Per-call cap the caller wants the screenshot to
                   fit. Same shape and semantics as `page_screenshot`'s
                   `image_cap`: `{"max_bytes": int, "max_dimension": int}`
                   — both optional. `max_bytes` switches output to JPEG
                   with a quality-step search (PNG → JPG extension
                   change). Falls back to `AI_DEV_BROWSER_IMAGE_CAP_MAX_BYTES`
                   / `AI_DEV_BROWSER_IMAGE_CAP_MAX_DIMENSION` env vars
                   when omitted. Precedence: per-call arg > env > None.

    Returns:
        dict with path, size, ref, width, height. With `image_cap`,
        also includes format ('PNG'|'JPEG') and capped (bool).
    """
    import datetime
    from pathlib import Path

    from .config import resolve_output_dir

    if path is None:
        out_dir = resolve_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = str(out_dir / f"{ts}_element.png")

    element = await get_element_by_ref(tab, ref)
    saved = await element.save_screenshot(path)

    # Resolve image_cap: per-call arg wins, else env var, else None.
    from . import _image_cap as _img_cap

    image_cap = _img_cap.resolve_cap(image_cap)

    if image_cap:
        cap_result = _img_cap.apply_image_cap(saved, image_cap)
        return {
            "path": cap_result["final_path"],
            "size": cap_result["final_bytes"],
            "ref": ref,
            "width": cap_result["final_width"],
            "height": cap_result["final_height"],
            "format": cap_result["format"],
            "capped": cap_result["capped"],
        }

    file_size = Path(saved).stat().st_size
    # Report dims even on the no-cap path so the return shape is stable
    # across with/without image_cap callers. PIL is optional; fall back
    # to (0, 0) if it isn't installed.
    try:
        from PIL import Image

        with Image.open(saved) as img:
            width, height = img.size
    except Exception:
        width = height = 0
    return {
        "path": saved,
        "size": file_size,
        "ref": ref,
        "width": width,
        "height": height,
    }


async def select_by_ref(
    tab: Tab,
    ref: str,
) -> dict:
    """Use when: you're picking an option inside a native `<select>`.
    Prereq: `page_discover()` → find the `<option>`'s ref → pass it here.
    Returns `{selected, ref}`. Don't use this for custom JS dropdowns
    (those aren't `<option>` elements — use `click_by_text` instead).

    Args:
        tab: Tab instance
        ref: Element ref of the <option> to select

    Returns:
        dict with selected status
    """
    element = await get_element_by_ref(tab, ref)
    await element.select_option()
    return {"selected": True, "ref": ref}


async def upload_by_ref(
    tab: Tab,
    ref: str,
    paths: str,
) -> dict:
    """Use when: you're filling a native `<input type="file">`. Prereq:
    `page_discover()` → find the file input's ref → pass it here with
    comma-separated absolute paths. Returns `{uploaded, ref, files}`.
    Don't use this for drag-and-drop upload zones (those aren't file
    inputs — use `mouse_drag` or a click + native dialog pattern).

    Args:
        tab: Tab instance
        ref: Element ref of the <input type="file">
        paths: Comma-separated file paths to upload

    Returns:
        dict with uploaded status and file count
    """
    element = await get_element_by_ref(tab, ref)
    file_list = [p.strip() for p in paths.split(",")]
    await element.send_file(*file_list)
    return {"uploaded": True, "ref": ref, "files": len(file_list)}


async def drag_by_ref(
    tab: Tab,
    ref: str,
    to_x: float,
    to_y: float,
    steps: int = 10,
) -> dict:
    """Use when: you need to reorder a list item, drag-drop a file onto a
    zone, or move a draggable. Prereq: `ref` of the source element +
    destination coordinates. Returns `{dragged, ref}`. For arbitrary
    coord-to-coord drags (no source element), use `mouse_drag`.

    Args:
        tab: Tab instance
        ref: Element ref to drag from
        to_x: Destination X coordinate
        to_y: Destination Y coordinate
        steps: Number of intermediate steps

    Returns:
        dict with dragged status
    """
    element = await get_element_by_ref(tab, ref)
    await element.mouse_drag(to_x, to_y, steps=steps)
    return {"dragged": True, "ref": ref}
