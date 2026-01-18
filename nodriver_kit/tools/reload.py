"""Reload the page.

CLI:
    python -m nodriver_kit.tools.reload

Python:
    from nodriver_kit.tools import reload
    result = await reload(tab)
"""

from nodriver_kit.core import reload as core_reload
from ._cli import as_cli


@as_cli
async def reload(tab) -> dict:
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
        return {"error": f"Reload failed: {e}"}


if __name__ == "__main__":
    reload.cli_main()
