"""Get text content of an element.

CLI:
    python -m nodriver_kit.tools.text_content --selector "h1"
    python -m nodriver_kit.tools.text_content --text "Welcome"

Python:
    from nodriver_kit.tools import text_content
    result = await text_content(tab, selector="h1")
"""

from nodriver_kit.core import find_element
from ._cli import as_cli


@as_cli
async def text_content(tab, selector: str = None, text: str = None) -> dict:
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
        return {"error": f"text_content failed: {e}"}


if __name__ == "__main__":
    text_content.cli_main()
