"""Find elements on the page.

CLI:
    python -m nodriver_kit.tools.find --text "Login"
    python -m nodriver_kit.tools.find --selector "button.submit"

Python:
    from nodriver_kit.tools import find
    result = await find(tab, text="Login")
"""

from nodriver_kit.core import find_element, find_elements
from ._cli import as_cli


@as_cli
async def find(tab, selector: str = None, text: str = None, all: bool = False) -> dict:
    """Find element(s) by selector or text.

    Args:
        tab: Browser tab
        selector: CSS selector
        text: Text content to find
        all: If True, find all matching elements

    Returns:
        {"found": True, "count": ...} on success
    """
    if not selector and not text:
        return {"error": "Must specify --selector or --text"}

    try:
        if all:
            elements = await find_elements(tab, text=text, selector=selector)
            return {
                "found": len(elements) > 0,
                "count": len(elements),
            }
        else:
            element = await find_element(tab, text=text, selector=selector)
            if element:
                # Get element info
                tag = await element.evaluate("this.tagName.toLowerCase()")
                text_content = await element.evaluate("this.textContent.slice(0, 100)")
                return {
                    "found": True,
                    "tag": tag,
                    "text": text_content.strip() if text_content else "",
                }
            else:
                return {"found": False}
    except Exception as e:
        return {"error": f"Find failed: {e}"}


if __name__ == "__main__":
    find.cli_main()
