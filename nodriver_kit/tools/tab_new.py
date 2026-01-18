"""Open a new tab.

CLI:
    python -m nodriver_kit.tools.tab_new --url "https://example.com"

Python:
    from nodriver_kit.tools import tab_new
    result = await tab_new(tab, url="https://example.com")
"""

from nodriver_kit.core import new_tab
from ._cli import as_cli


@as_cli
async def tab_new(tab, url: str = None) -> dict:
    """Open a new tab.

    Args:
        tab: Browser tab (used to get browser reference)
        url: URL to open in new tab (optional)

    Returns:
        {"opened": True, "url": ...}
    """
    try:
        new = await new_tab(tab, url=url)
        return {
            "opened": True,
            "url": new.url if hasattr(new, 'url') else url,
        }
    except Exception as e:
        return {"error": f"New tab failed: {e}"}


if __name__ == "__main__":
    tab_new.cli_main()
