"""Get accessibility tree of the page.

CLI:
    python -m nodriver_kit.tools.ax_tree
    python -m nodriver_kit.tools.ax_tree --interactable-only

Python:
    from nodriver_kit.tools import ax_tree
    result = await ax_tree(tab, interactable_only=True)
"""

from nodriver_kit.core import get_snapshot
from ._cli import as_cli


@as_cli()
async def ax_tree(tab, interactable_only: bool = False) -> dict:
    """Get accessibility tree of the page.

    Returns elements with ref IDs that can be used with ax_select.

    Args:
        tab: Browser tab
        interactable_only: If True, only return interactable elements

    Returns:
        List of elements: [{"ref": "1", "role": "button", "name": "Submit"}, ...]
    """
    try:
        result = await get_snapshot(tab, interactable_only=interactable_only)
        return result
    except Exception as e:
        return {"error": f"ax_tree failed: {e}"}


if __name__ == "__main__":
    ax_tree.cli_main()
