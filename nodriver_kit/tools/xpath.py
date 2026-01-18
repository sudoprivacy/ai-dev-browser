"""Find elements by XPath.

CLI:
    python -m nodriver_kit.tools.xpath --expr "//button[@type='submit']"

Python:
    from nodriver_kit.tools import xpath
    result = await xpath(tab, expr="//button[@type='submit']")
"""

from nodriver_kit.core import find_by_xpath
from ._cli import as_cli


@as_cli
async def xpath(tab, expr: str) -> dict:
    """Find elements by XPath expression.

    Args:
        tab: Browser tab
        expr: XPath expression

    Returns:
        {"found": True, "count": ...} on success
    """
    try:
        elements = await find_by_xpath(tab, expr)
        return {
            "found": len(elements) > 0,
            "count": len(elements),
        }
    except Exception as e:
        return {"error": f"XPath search failed: {e}"}


if __name__ == "__main__":
    xpath.cli_main()
