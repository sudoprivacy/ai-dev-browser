"""List all frames (iframes) on the page.

CLI:
    python -m ai_dev_browser.tools.list_frames

Python:
    from ai_dev_browser.tools import list_frames
    result = await list_frames(tab)
"""

import nodriver.cdp.page as page
from ._cli import as_cli


@as_cli()
async def list_frames(tab) -> list:
    """List all frames (iframes) on the page.

    Use frame IDs with ax_tree(frame_id=...) to get accessibility tree
    for specific iframes.

    Args:
        tab: Browser tab

    Returns:
        List of frames: [{"id": "ABC123", "url": "...", "name": "..."}, ...]
    """
    try:
        # Get frame tree
        result = await tab.send(page.get_frame_tree())

        frames = []

        def collect_frames(frame_tree, parent_id=None):
            frame = frame_tree.frame
            frames.append(
                {
                    "id": frame.id_,
                    "url": frame.url,
                    "name": frame.name if frame.name else None,
                    "parent_id": parent_id,
                }
            )
            if frame_tree.child_frames:
                for child in frame_tree.child_frames:
                    collect_frames(child, frame.id_)

        collect_frames(result)
        return frames
    except Exception as e:
        return {"error": f"list_frames failed: {e}"}


if __name__ == "__main__":
    list_frames.cli_main()
