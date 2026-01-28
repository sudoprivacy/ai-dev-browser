"""Get page HTML."""

from .._cli import as_cli


@as_cli()
async def page_html(tab, outer: bool = False) -> dict:
    """Get page HTML.

    Args:
        tab: Browser tab
        outer: If True, get outerHTML of document element
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
        return {"error": f"page_html failed: {e}"}


if __name__ == "__main__":
    page_html.cli_main()
