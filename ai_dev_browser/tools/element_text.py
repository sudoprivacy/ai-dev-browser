"""Get text content of an element."""

from ai_dev_browser.core import find_element
from .._cli import as_cli


@as_cli()
async def element_text(tab, selector: str = None, text: str = None) -> dict:
    """Get text content of an element.

    Args:
        tab: Browser tab
        selector: CSS selector
        text: Text to find element by
    """
    if not selector and not text:
        return {"error": "Must specify --selector or --text"}

    try:
        element = await find_element(tab, text=text, selector=selector)
        if element:
            content = await element.text
            return {"text": content if content else ""}
        else:
            return {"error": "Element not found"}
    except Exception as e:
        return {"error": f"element_text failed: {e}"}


if __name__ == "__main__":
    element_text.cli_main()
