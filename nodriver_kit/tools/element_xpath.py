"""Find elements by XPath.

CLI:
    python -m nodriver_kit.tools.element_xpath --expr "//button[@type='submit']"

Python:
    from nodriver_kit.tools import element_xpath
    result = await element_xpath(tab, expr="//button[@type='submit']")

Note:
    Git Bash/MSYS2 on Windows converts // to / (UNC path handling).
    Use PowerShell or cmd.exe for XPath expressions starting with //.
"""

from nodriver_kit.core import find_by_xpath
from ._cli import as_cli


@as_cli()
async def element_xpath(tab, expr: str) -> dict:
    """Find elements by XPath expression.

    Args:
        tab: Browser tab
        expr: XPath expression

    Returns:
        {"found": True, "count": ...} on success
    """
    try:
        elements = await find_by_xpath(tab, xpath=expr)
        return {
            "found": len(elements) > 0,
            "count": len(elements),
        }
    except Exception as e:
        return {"error": f"element_xpath failed: {e}"}


if __name__ == "__main__":
    element_xpath.cli_main()
