"""Navigate to a URL.

CLI:
    python -m nodriver_kit.tools.page_goto --url "https://example.com"

Python:
    from nodriver_kit.tools import page_goto
    result = await page_goto(tab, url="https://example.com")
"""

from nodriver_kit.core import goto as core_goto
from ._cli import as_cli


@as_cli()
async def page_goto(tab, url: str) -> dict:
    """Navigate to a URL.

    Args:
        tab: Browser tab
        url: URL to navigate to

    Returns:
        {"url": ..., "title": ...} on success
    """
    try:
        await core_goto(tab, url)
        title = await tab.evaluate("document.title")
        return {
            "url": tab.url,
            "title": title,
            "success": True,
        }
    except Exception as e:
        return {"error": f"page_goto failed: {e}"}


if __name__ == "__main__":
    page_goto.cli_main()
