"""Get accessibility tree of the page."""

from ai_dev_browser.core import get_snapshot
from .._cli import as_cli


@as_cli()
async def ax_tree(
    tab, interactable_only: bool = False, include_iframes: bool = True
) -> dict:
    """Get accessibility tree of the page.

    Returns elements with ref IDs that can be used with ax_select.
    By default, includes all iframes. Iframe elements have refs like "FRAME_xxx:1".

    Args:
        tab: Browser tab
        interactable_only: If True, only return interactable elements
        include_iframes: If True (default), include iframe content
    """
    try:
        result = await get_snapshot(
            tab, interactable_only=interactable_only, include_iframes=include_iframes
        )
        return result
    except Exception as e:
        return {"error": f"ax_tree failed: {e}"}


if __name__ == "__main__":
    ax_tree.cli_main()
