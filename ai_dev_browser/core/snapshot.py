"""AI-friendly page snapshot using accessibility tree."""

import nodriver
import nodriver.cdp.accessibility as accessibility
import nodriver.cdp.page as page


def _format_ax_node(
    node,
    ref_counter: list,
    max_depth: int,
    current_depth: int = 0,
    interactable_only: bool = False,
) -> list[dict]:
    """Format an accessibility node into AI-friendly structure."""
    results: list[dict] = []

    if current_depth > max_depth:
        return results

    # Extract properties
    props = {}
    if hasattr(node, "properties") and node.properties:
        for prop in node.properties:
            if hasattr(prop, "name") and hasattr(prop, "value"):
                name = prop.name.value if hasattr(prop.name, "value") else str(prop.name)
                val = prop.value.value if hasattr(prop.value, "value") else prop.value
                props[name] = val

    role = node.role.value if hasattr(node, "role") and node.role else None
    name = node.name.value if hasattr(node, "name") and node.name else None

    # Skip ignored nodes
    if role in ("none", "generic", "InlineTextBox", "LineBreak"):
        if hasattr(node, "children") and node.children:
            for child in node.children:
                results.extend(
                    _format_ax_node(
                        child,
                        ref_counter,
                        max_depth,
                        current_depth + 1,
                        interactable_only,
                    )
                )
        return results

    # Interactable roles
    interactable_roles = {
        "button",
        "link",
        "textbox",
        "checkbox",
        "radio",
        "combobox",
        "listbox",
        "option",
        "menuitem",
        "tab",
        "switch",
        "slider",
        "spinbutton",
        "searchbox",
        "menu",
        "menubar",
    }
    is_interactable = role in interactable_roles or props.get("focusable", False)

    # Skip non-interactable if filter is on
    if interactable_only and not is_interactable and role not in ("heading", "img", "alert"):
        if hasattr(node, "children") and node.children:
            for child in node.children:
                results.extend(
                    _format_ax_node(
                        child,
                        ref_counter,
                        max_depth,
                        current_depth + 1,
                        interactable_only,
                    )
                )
        return results

    # Build node info
    if role and (name or is_interactable):
        ref_counter[0] += 1

        # Get node_id first so we can encode it in ref
        node_id = None
        if hasattr(node, "backend_dom_node_id") and node.backend_dom_node_id:
            node_id = node.backend_dom_node_id
            # Extract int from BackendNodeId
            try:
                node_id = int(node_id)
            except (TypeError, ValueError):
                node_id = None

        # Build ref with embedded node_id: "9#214" or just "9" if no node_id
        ref_str = str(ref_counter[0])
        if node_id is not None:
            ref_str = f"{ref_counter[0]}#{node_id}"

        info = {
            "ref": ref_str,
            "role": role,
        }

        if name:
            info["name"] = name[:100]

        if hasattr(node, "value") and node.value:
            val = node.value.value if hasattr(node.value, "value") else str(node.value)
            if val:
                info["value"] = val[:50]

        # States
        if props.get("focused"):
            info["focused"] = True
        if props.get("disabled"):
            info["disabled"] = True
        if props.get("required"):
            info["required"] = True
        if props.get("checked") is not None:
            info["checked"] = props["checked"]
        if props.get("selected"):
            info["selected"] = True
        if props.get("expanded") is not None:
            info["expanded"] = props["expanded"]

        if role == "heading" and props.get("level"):
            info["level"] = props["level"]

        results.append(info)

    # Process children
    if hasattr(node, "children") and node.children:
        for child in node.children:
            results.extend(
                _format_ax_node(child, ref_counter, max_depth, current_depth + 1, interactable_only)
            )

    return results


async def _get_all_frames(tab) -> list[dict]:
    """Get all frames in the page."""
    try:
        result = await tab.send(page.get_frame_tree())
        frames = []

        def collect_frames(frame_tree, is_main=True):
            frame = frame_tree.frame
            frames.append(
                {
                    "id": frame.id_,
                    "url": frame.url,
                    "is_main": is_main,
                }
            )
            if frame_tree.child_frames:
                for child in frame_tree.child_frames:
                    collect_frames(child, is_main=False)

        collect_frames(result)
        return frames
    except Exception:
        return []


async def _get_frame_nodes(
    tab,
    frame_id: str | None,
    interactable_only: bool,
    max_depth: int,
    ref_prefix: str = "",
) -> list:
    """Get accessibility nodes for a specific frame."""
    frame = page.FrameId(frame_id) if frame_id else None
    result = await tab.send(accessibility.get_full_ax_tree(frame_id=frame))

    if not result:
        return []

    ax_nodes = result.nodes if hasattr(result, "nodes") else result
    if not ax_nodes:
        return []

    ref_counter = [0]
    nodes = []

    for node in ax_nodes:
        if hasattr(node, "role") and node.role:
            formatted = _format_ax_node(
                node,
                ref_counter,
                max_depth,
                interactable_only=interactable_only,
            )
            nodes.extend(formatted)

    # Add prefix to refs for non-main frames
    if ref_prefix:
        for n in nodes:
            n["ref"] = f"{ref_prefix}:{n['ref']}"

    # Remove duplicates within this frame
    seen_refs = set()
    unique_nodes = []
    for n in nodes:
        ref = n.get("ref")
        if ref not in seen_refs:
            seen_refs.add(ref)
            unique_nodes.append(n)

    return unique_nodes


async def _get_snapshot(
    tab: nodriver.Tab,
    interactable_only: bool = False,
    max_depth: int = 10,
    frame_id: str | None = None,
    include_iframes: bool = True,
) -> list:
    """Get AI-friendly accessibility tree snapshot.

    This is the key AI feature - returns semantic page structure
    instead of raw HTML.

    Args:
        tab: Tab instance
        interactable_only: If True, only return buttons, links, inputs, etc.
        max_depth: Maximum tree depth to traverse
        frame_id: If specified, only get accessibility tree for this frame.
        include_iframes: If True (default), include all iframes in the result.
                         Iframe elements have refs like "FRAME_xxx:1".

    Returns:
        List of nodes with role, name, and state info.
        Main frame elements have simple refs: "1", "2", etc.
        Iframe elements have prefixed refs: "FRAME_ABC123:1", "FRAME_ABC123:2", etc.

    Example:
        [
            {"ref": "1", "role": "button", "name": "Sign in"},
            {"ref": "2", "role": "textbox", "name": "Email", "focused": True},
            {"ref": "FRAME_ABC123:1", "role": "button", "name": "Submit"},
        ]
    """
    # Enable accessibility domain
    await tab.send(accessibility.enable())

    # If specific frame requested, just get that frame
    if frame_id:
        return await _get_frame_nodes(tab, frame_id, interactable_only, max_depth, ref_prefix="")

    # Get main frame nodes
    all_nodes = await _get_frame_nodes(tab, None, interactable_only, max_depth, ref_prefix="")

    # If not including iframes, return just main frame
    if not include_iframes:
        return all_nodes

    # Get all frames and add iframe content
    frames = await _get_all_frames(tab)
    for frame in frames:
        if frame["is_main"]:
            continue  # Already got main frame

        # Skip about:blank and other non-content frames
        if frame["url"].startswith("about:"):
            continue

        try:
            iframe_nodes = await _get_frame_nodes(
                tab,
                frame["id"],
                interactable_only,
                max_depth,
                ref_prefix=f"FRAME_{frame['id'][:8]}",  # Use first 8 chars of frame ID
            )
            all_nodes.extend(iframe_nodes)
        except Exception:
            # Some frames may not be accessible, skip them
            pass

    return all_nodes


async def _get_accessibility_tree(
    tab: nodriver.Tab,
    interactable_only: bool = False,
    include_iframes: bool = True,
) -> dict:
    """Get accessibility tree with metadata.

    Wrapper around get_snapshot that returns a dict with elements and count.

    Args:
        tab: Tab instance
        interactable_only: If True, only return interactable elements
        include_iframes: If True (default), include iframe content

    Returns:
        dict with elements list and count
    """
    elements = await _get_snapshot(
        tab,
        interactable_only=interactable_only,
        include_iframes=include_iframes,
    )
    return {"elements": elements, "count": len(elements)}


async def find(
    tab: nodriver.Tab,
    text: str | None = None,
    interactable_only: bool = True,
    include_coordinates: bool = True,
    include_iframes: bool = True,
) -> dict:
    """Find elements on the page - the main discovery tool for AI.

    Returns interactive elements with their refs (for click_ref) and
    coordinates (for mouse_click). Use this to discover what's on the page
    before clicking.

    Args:
        tab: Tab instance
        text: Optional text filter (case-insensitive substring match)
        interactable_only: If True (default), only return interactive elements
        include_coordinates: If True (default), include x/y coordinates
        include_iframes: If True (default), include iframe content

    Returns:
        dict with elements list, each containing:
        - ref: reference for click_ref (e.g., "5#214")
        - role: element role (button, link, textbox, etc.)
        - name: accessible name
        - x, y: center coordinates (if include_coordinates=True)
        - box: {left, top, right, bottom} (if include_coordinates=True)

    Example:
        find()                    # All interactive elements
        find(text="登录")         # Filter by text
        find(text="Sign")         # Case-insensitive match
    """
    import nodriver.cdp.dom as dom

    # Get accessibility tree
    elements = await _get_snapshot(
        tab,
        interactable_only=interactable_only,
        include_iframes=include_iframes,
    )

    # Filter by text if specified
    if text:
        text_lower = text.lower()
        elements = [
            el for el in elements
            if text_lower in (el.get("name") or "").lower()
        ]

    # Add coordinates if requested
    if include_coordinates:
        for el in elements:
            ref = el.get("ref", "")
            # Extract node_id from ref (format: "5#214" or "FRAME_xxx:5#214")
            node_id = None
            if "#" in ref:
                try:
                    node_id_str = ref.split("#")[-1]
                    node_id = int(node_id_str)
                except (ValueError, IndexError):
                    pass

            if node_id:
                try:
                    backend_node_id = dom.BackendNodeId(node_id)
                    box = await tab.send(dom.get_box_model(backend_node_id=backend_node_id))
                    if box and box.content:
                        quad = box.content
                        # Calculate center
                        x = (quad[0] + quad[2] + quad[4] + quad[6]) / 4
                        y = (quad[1] + quad[3] + quad[5] + quad[7]) / 4
                        el["x"] = round(x)
                        el["y"] = round(y)
                        # Calculate bounding box
                        left = min(quad[0], quad[2], quad[4], quad[6])
                        top = min(quad[1], quad[3], quad[5], quad[7])
                        right = max(quad[0], quad[2], quad[4], quad[6])
                        bottom = max(quad[1], quad[3], quad[5], quad[7])
                        el["box"] = {
                            "left": round(left),
                            "top": round(top),
                            "right": round(right),
                            "bottom": round(bottom),
                        }
                except Exception:
                    # Skip coordinates for this element if we can't get them
                    pass

    return {"elements": elements, "count": len(elements)}
