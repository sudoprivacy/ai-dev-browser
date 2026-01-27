"""Find elements on the page."""

from ai_dev_browser.core import find_element, find_elements
from ._cli import as_cli


@as_cli()
async def element_find(tab, selector: str = None, text: str = None, all: bool = False) -> dict:
    """Find element(s) by selector or text.

    Args:
        tab: Browser tab
        selector: CSS selector
        text: Text content to find
        all: If True, find all matching elements
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
                tag = await element.apply("(el) => el.tagName.toLowerCase()")
                text_content = await element.apply("(el) => el.textContent.slice(0, 100)")
                return {
                    "found": True,
                    "tag": tag,
                    "text": text_content.strip() if text_content else "",
                }
            else:
                return {"found": False}
    except Exception as e:
        return {"error": f"element_find failed: {e}"}


if __name__ == "__main__":
    element_find.cli_main()
