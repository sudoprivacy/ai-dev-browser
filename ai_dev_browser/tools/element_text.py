"""Get text content of an element.

CLI:
    python -m ai_dev_browser.tools.element_text --selector "h1"
    python -m ai_dev_browser.tools.element_text --text "Welcome"

Python:
    from ai_dev_browser.tools import element_text
    result = await element_text(tab, selector="h1")
"""

from ai_dev_browser.core import find_element
from ._cli import as_cli


@as_cli()
async def element_text(tab, selector: str = None, text: str = None) -> dict:
    """Get text content of an element.

    Args:
        tab: Browser tab
        selector: CSS selector
        text: Text to find element by

    Returns:
        {"text": "..."} with the element's text content
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
