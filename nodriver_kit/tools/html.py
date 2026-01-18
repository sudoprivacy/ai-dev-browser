"""Get page HTML.

CLI:
    python -m nodriver_kit.tools.html

Python:
    from nodriver_kit.tools import html
    result = await html(tab)
"""

from ._cli import as_cli


@as_cli
async def html(tab, outer: bool = False) -> dict:
    """Get page HTML.

    Args:
        tab: Browser tab
        outer: If True, get outerHTML of document element

    Returns:
        {"html": ..., "length": ...}
    """
    try:
        if outer:
            content = await tab.evaluate("document.documentElement.outerHTML")
        else:
            content = await tab.evaluate("document.documentElement.innerHTML")
        return {
            "html": content,
            "length": len(content),
        }
    except Exception as e:
        return {"error": f"Get HTML failed: {e}"}


if __name__ == "__main__":
    html.cli_main()
