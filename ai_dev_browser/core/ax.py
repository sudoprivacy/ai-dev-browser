"""Accessibility tree operations for element interaction."""

import asyncio
import contextlib
import re

import nodriver
import nodriver.cdp.dom as dom
import nodriver.cdp.input_ as cdp_input
import nodriver.cdp.page as page

from .snapshot import get_snapshot


def _parse_ref(ref: str) -> tuple[str | None, str, int | None]:
    """Parse ref to extract frame prefix, local ref, and embedded node_id.

    Ref format: "index#nodeId" or "FRAME_xxx:index#nodeId"
    Examples:
        "9#214" -> (None, "9", 214)
        "FRAME_ABC123:9#214" -> ("FRAME_ABC123", "9", 214)
        "9" -> (None, "9", None)  # legacy format without node_id

    Returns:
        (frame_id_prefix, local_ref, node_id)
    """
    frame_prefix = None
    local_ref = ref
    node_id = None

    # Check for frame prefix
    frame_match = re.match(r"^(FRAME_[^:]+):(.+)$", ref)
    if frame_match:
        frame_prefix = frame_match.group(1)
        local_ref = frame_match.group(2)

    # Check for embedded node_id
    node_match = re.match(r"^(\d+)#(\d+)$", local_ref)
    if node_match:
        local_ref = node_match.group(1)
        node_id = int(node_match.group(2))

    return frame_prefix, local_ref, node_id


async def _get_frame_id_by_prefix(tab: nodriver.Tab, prefix: str) -> str | None:
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


async def click_by_node_id(
    tab: nodriver.Tab,
    node_id: int,
) -> dict:
    """Click element by backend node ID via CDP.

    Args:
        tab: Tab instance
        node_id: Backend DOM node ID

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

        # Dispatch mouse events
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


async def wait_for_ax_element(
    tab: nodriver.Tab,
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
            elements = await get_snapshot(tab)
            for el in elements:
                role_match = wait_for_role is None or el.get("role") == wait_for_role
                name_match = wait_for_name is None or wait_for_name in el.get("name", "")
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


async def click_ax_element(
    tab: nodriver.Tab,
    ref: str | None = None,
    node_id: int | None = None,
    wait_for_role: str | None = None,
    wait_for_name: str | None = None,
    wait_timeout: float = 5.0,
    wait_interval: float = 0.3,
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
        result = await click_by_node_id(tab, node_id)
        if result.get("clicked") and (wait_for_role or wait_for_name):
            waited = await wait_for_ax_element(
                tab, wait_for_role, wait_for_name, wait_timeout, wait_interval
            )
            if waited.get("found") and not waited.get("skipped"):
                result["waited_for"] = waited.get("element")
            elif waited.get("timeout"):
                result["wait_timeout"] = True
        return result

    # Parse ref to extract frame prefix, local ref, and embedded node_id
    frame_prefix, local_ref, embedded_node_id = _parse_ref(ref)

    # If ref contains embedded node_id, use it directly (most reliable)
    if embedded_node_id is not None:
        result = await click_by_node_id(tab, embedded_node_id)
        if result.get("clicked"):
            result["ref"] = ref
            if wait_for_role or wait_for_name:
                waited = await wait_for_ax_element(
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
    elements = await get_snapshot(tab, frame_id=frame_id)

    # Find element by local ref (without frame prefix or node_id suffix)
    target = None
    for el in elements:
        # Match by index part only (el.ref might be "9#214", we want to match "9")
        el_ref = el.get("ref", "")
        el_index = el_ref.split("#")[0] if "#" in el_ref else el_ref
        if el_index == local_ref:
            target = el
            break

    if not target:
        return {"error": f"Element with ref '{ref}' not found"}

    # Extract node_id from target's ref
    target_ref = target.get("ref", "")
    target_node_id = None
    if "#" in target_ref:
        with contextlib.suppress(ValueError):
            target_node_id = int(target_ref.split("#")[1])

    if not target_node_id:
        return {"error": f"Element ref '{ref}' has no nodeId"}

    # Click the element
    result = await click_by_node_id(tab, target_node_id)
    if result.get("clicked"):
        result["ref"] = ref
        result["element"] = {
            "role": target.get("role"),
            "name": target.get("name"),
        }
        if wait_for_role or wait_for_name:
            waited = await wait_for_ax_element(
                tab, wait_for_role, wait_for_name, wait_timeout, wait_interval
            )
            if waited.get("found") and not waited.get("skipped"):
                result["waited_for"] = waited.get("element")
            elif waited.get("timeout"):
                result["wait_timeout"] = True

    return result


async def click_ref(
    tab: nodriver.Tab,
    ref: str,
) -> dict:
    """Click element by ref from find().

    This is the primary way for AI to click elements by ref. Use find() first
    to get element refs, then click_ref with the ref string.

    Args:
        tab: Tab instance
        ref: Element ref from find() (e.g., "5#214" or "FRAME_ABC123:5#214")

    Returns:
        dict with clicked status and element info

    Example:
        # First find elements
        result = find()
        # Then click by ref
        click_ref("5#214")
    """
    return await click_ax_element(tab, ref=ref)


async def focus_by_ref(
    tab: nodriver.Tab,
    ref: str,
) -> dict:
    """Focus element by ref from find().

    Use find() first to get element refs, then focus_by_ref.
    Useful when you need to focus without clicking (e.g., to avoid
    triggering click handlers).

    Args:
        tab: Tab instance
        ref: Element ref from find() (e.g., "5#214")

    Returns:
        dict with focused status

    Example:
        focus_by_ref("5#214")
    """
    # Parse ref to extract node_id
    _, _, node_id = _parse_ref(ref)

    if node_id is None:
        return {"focused": False, "error": f"Invalid ref format: {ref}"}

    try:
        backend_node_id = dom.BackendNodeId(node_id)
        await tab.send(dom.focus(backend_node_id=backend_node_id))
        return {"focused": True, "ref": ref}
    except Exception as e:
        return {"focused": False, "error": str(e)}


async def type_by_ref(
    tab: nodriver.Tab,
    ref: str,
    text: str,
    clear: bool = False,
) -> dict:
    """Type text into element by ref from find().

    Use find() first to get element refs, then type_by_ref.

    Args:
        tab: Tab instance
        ref: Element ref from find() (e.g., "5#214")
        text: Text to type into the element
        clear: If True, clear existing content first

    Returns:
        dict with typed status

    Example:
        type_by_ref("5#214", "myusername")
        type_by_ref("5#214", "newvalue", clear=True)
    """
    # First focus the element
    focus_result = await focus_by_ref(tab, ref)
    if not focus_result.get("focused"):
        return {"typed": False, "error": focus_result.get("error", "Focus failed")}

    # Clear if requested (select all + delete)
    if clear:
        # Select all
        await tab.send(
            cdp_input.dispatch_key_event(
                type_="keyDown",
                modifiers=2,  # Ctrl/Cmd
                key="a",
                code="KeyA",
            )
        )
        await tab.send(
            cdp_input.dispatch_key_event(
                type_="keyUp",
                modifiers=2,
                key="a",
                code="KeyA",
            )
        )
        # Delete
        await tab.send(
            cdp_input.dispatch_key_event(
                type_="keyDown",
                key="Backspace",
                code="Backspace",
            )
        )
        await tab.send(
            cdp_input.dispatch_key_event(
                type_="keyUp",
                key="Backspace",
                code="Backspace",
            )
        )

    # Type text using insertText (most reliable for input fields)
    await tab.send(
        cdp_input.insert_text(text=text)
    )

    return {"typed": True, "ref": ref, "text": text}
