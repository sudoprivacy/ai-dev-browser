"""Reload the page.

CLI:
    python -m nodriver_kit.tools.page_reload

Python:
    from nodriver_kit.tools import page_reload
    result = await page_reload(tab)
"""

from nodriver_kit.core import reload as core_reload
from ._cli import as_cli


@as_cli
async def page_reload(tab) -> dict:
    """Reload the current page.

    Args:
        tab: Browser tab

    Returns:
        {"reloaded": True} on success
    """
    try:
        await core_reload(tab)
        return {"reloaded": True, "url": tab.url}
    except Exception as e:
        return {"error": f"page_reload failed: {e}"}


if __name__ == "__main__":
    page_reload.cli_main()
