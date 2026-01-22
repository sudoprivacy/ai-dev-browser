"""Click an element on the page.

CLI:
    python -m nodriver_kit.tools.element_click --selector "button.submit"
    python -m nodriver_kit.tools.element_click --text "Login"

Python:
    from nodriver_kit.tools import element_click
    result = await element_click(tab, selector="button.submit")
"""

from nodriver_kit.core import click as core_click
from ._cli import as_cli


@as_cli()
async def element_click(tab, selector: str = None, text: str = None) -> dict:
    """Click an element by selector or text.

    Args:
        tab: Browser tab
        selector: CSS selector
        text: Text content to find

    Returns:
        {"clicked": True} on success
    """
    if not selector and not text:
        return {"error": "Must specify --selector or --text"}

    try:
        success = await core_click(tab, text=text, selector=selector)
        if success:
            return {"clicked": True}
        else:
            return {"error": "Element not found"}
    except Exception as e:
        return {"error": f"element_click failed: {e}"}


if __name__ == "__main__":
    element_click.cli_main()
