"""Open a new tab."""

from ai_dev_browser.core import new_tab

from .._cli import as_cli


@as_cli()
async def tab_new(tab, url: str = None) -> dict:
    """Open a new tab.

    Args:
        tab: Browser tab (used to get browser reference)
        url: URL to open in new tab (optional)
    """
    try:
        new = await new_tab(tab, url=url)
        return {
            "opened": True,
            "url": new.url if hasattr(new, "url") else url,
        }
    except Exception as e:
        return {"error": f"New tab failed: {e}"}


if __name__ == "__main__":
    tab_new.cli_main()
