"""Reload the page."""

from ai_dev_browser.core import reload as core_reload
from .._cli import as_cli


@as_cli()
async def page_reload(tab) -> dict:
    """Reload the current page.

    Args:
        tab: Browser tab
    """
    try:
        await core_reload(tab)
        return {"reloaded": True, "url": tab.url}
    except Exception as e:
        return {"error": f"page_reload failed: {e}"}


if __name__ == "__main__":
    page_reload.cli_main()
