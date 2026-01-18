"""Get AI-friendly page snapshot (accessibility tree).

CLI:
    python -m nodriver_kit.tools.snapshot
    python -m nodriver_kit.tools.snapshot --interactable-only

Python:
    from nodriver_kit.tools import snapshot
    result = await snapshot(tab, interactable_only=True)
"""

from nodriver_kit.core import get_snapshot
from ._cli import as_cli


@as_cli
async def snapshot(tab, interactable_only: bool = False) -> dict:
    """Get AI-friendly page snapshot.

    Args:
        tab: Browser tab
        interactable_only: If True, only return interactable elements

    Returns:
        {"snapshot": ..., "element_count": ...}
    """
    try:
        result = await get_snapshot(tab, interactable_only=interactable_only)
        return result
    except Exception as e:
        return {"error": f"Snapshot failed: {e}"}


if __name__ == "__main__":
    snapshot.cli_main()
