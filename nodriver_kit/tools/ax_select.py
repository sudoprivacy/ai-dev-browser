"""Select and click element by accessibility tree ref.

CLI:
    python -m nodriver_kit.tools.ax_select --ref 5

Python:
    from nodriver_kit.tools import ax_select
    result = await ax_select(tab, ref="5")
"""

import nodriver.cdp.dom as dom
import nodriver.cdp.input_ as cdp_input

from nodriver_kit.core import get_snapshot
from ._cli import as_cli


async def _click_by_node_id(tab, node_id) -> bool:
    """Click element by backend node id via CDP."""
    try:
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


@as_cli
async def ax_select(tab, ref: str) -> dict:
    """Select and click element by accessibility tree ref.

    Use ax_tree to get element refs, then ax_select to interact with them.

    Args:
        tab: Browser tab
        ref: Element ref from ax_tree (e.g., "5")

    Returns:
        {"clicked": True, "element": {...}} on success
    """
    try:
        # Get accessibility tree with nodeIds
        elements = await get_snapshot(tab)

        # Find element by ref
        target = None
        for el in elements:
            if el.get("ref") == ref:
                target = el
                break

        if not target:
            return {"error": f"Element with ref '{ref}' not found"}

        node_id = target.get("_nodeId")
        if not node_id:
            return {"error": f"Element ref '{ref}' has no nodeId"}

        # Click the element
        success = await _click_by_node_id(tab, node_id)
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
