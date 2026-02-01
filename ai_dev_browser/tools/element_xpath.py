"""Find elements by XPath."""

from ai_dev_browser.core import find_by_xpath

from .._cli import as_cli


@as_cli()
async def element_xpath(tab, expr: str) -> dict:
    """Find elements by XPath expression.

    Args:
        tab: Browser tab
        expr: XPath expression
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
