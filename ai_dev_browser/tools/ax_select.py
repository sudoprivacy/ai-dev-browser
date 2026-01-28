"""Select and click element by accessibility tree ref."""

import re

import nodriver.cdp.dom as dom
import nodriver.cdp.input_ as cdp_input
import nodriver.cdp.page as page

from ai_dev_browser.core import get_snapshot
from .._cli import as_cli


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


async def _get_frame_id_by_prefix(tab, prefix: str) -> str | None:
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


async def _click_by_node_id(tab, node_id) -> bool:
    """Click element by backend node id via CDP."""
    try:
        # Wrap int in BackendNodeId if needed
        if isinstance(node_id, int):
            node_id = dom.BackendNodeId(node_id)
        # Get box model for the node
        box = await tab.send(dom.get_box_model(backend_node_id=node_id))
        if not box or not box.content:
            return False

        # Get center of content box (content quad has 8 values: 4 x,y pairs)
        quad = box.content
        x = (quad[0] + quad[2] + quad[4] + quad[6]) / 4
        y = (quad[1] + quad[3] + quad[5] + quad[7]) / 4

        # Dispatch mouse events
        await tab.send(cdp_input.dispatch_mouse_event(
            type_="mousePressed",
            x=x, y=y,
            button=cdp_input.MouseButton.LEFT,
            click_count=1
        ))
        await tab.send(cdp_input.dispatch_mouse_event(
            type_="mouseReleased",
            x=x, y=y,
            button=cdp_input.MouseButton.LEFT,
            click_count=1
        ))
        return True
    except Exception:
        return False


@as_cli()
async def ax_select(tab, ref: str = None, node_id: int = None) -> dict:
    """Select and click element by accessibility tree ref or node_id.

    Use ax_tree to get element refs, then ax_select to interact with them.
    For stable clicks, pass node_id directly from ax_tree result's _nodeId.

    Supports iframe elements with prefixed refs like "FRAME_ABC123:5".

    Args:
        tab: Browser tab
        ref: Element ref from ax_tree (e.g., "5" or "FRAME_ABC123:5")
        node_id: Backend node ID from ax_tree's _nodeId - direct click, no re-fetch
    """
    try:
        # Must specify at least one of ref or node_id
        if ref is None and node_id is None:
            return {"error": "Must specify --ref or --node-id"}

        # If node_id provided directly, use it (stable, no re-fetch)
        if node_id is not None:
            success = await _click_by_node_id(tab, node_id)
            if success:
                return {"clicked": True, "node_id": node_id}
            else:
                return {"error": f"Failed to click node_id '{node_id}'"}

        # Parse ref to extract frame prefix, local ref, and embedded node_id
        frame_prefix, local_ref, embedded_node_id = _parse_ref(ref)

        # If ref contains embedded node_id, use it directly (most reliable)
        if embedded_node_id is not None:
            success = await _click_by_node_id(tab, embedded_node_id)
            if success:
                return {"clicked": True, "ref": ref, "node_id": embedded_node_id}
            else:
                return {"error": f"Failed to click ref '{ref}' (node_id={embedded_node_id})"}

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
            try:
                target_node_id = int(target_ref.split("#")[1])
            except ValueError:
                pass

        if not target_node_id:
            return {"error": f"Element ref '{ref}' has no nodeId"}

        # Click the element
        success = await _click_by_node_id(tab, target_node_id)
        if success:
            return {
                "clicked": True,
                "element": {
                    "ref": target.get("ref"),
                    "role": target.get("role"),
                    "name": target.get("name"),
                }
            }
        else:
            return {"error": f"Failed to click element ref '{ref}'"}

    except Exception as e:
        return {"error": f"ax_select failed: {e}"}


if __name__ == "__main__":
    ax_select.cli_main()
