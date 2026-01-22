"""Focus an element on the page.

CLI:
    python -m ai_dev_browser.tools.element_focus --selector "input[name='email']"
    python -m ai_dev_browser.tools.element_focus --text "Email"

Python:
    from ai_dev_browser.tools import element_focus
    result = await element_focus(tab, selector="input[name='email']")
"""

from ai_dev_browser.core import find_element
from ._cli import as_cli


@as_cli()
async def element_focus(tab, selector: str = None, text: str = None) -> dict:
    """Focus an element by selector or text.

    Useful for input fields before typing.

    Args:
        tab: Browser tab
        selector: CSS selector
        text: Text content to find

    Returns:
        {"focused": True} on success
    """
    if not selector and not text:
        return {"error": "Must specify --selector or --text"}

    try:
        element = await find_element(tab, text=text, selector=selector)
        if element:
            await element.focus()
            return {"focused": True}
        else:
            return {"error": "Element not found"}
    except Exception as e:
        return {"error": f"element_focus failed: {e}"}


if __name__ == "__main__":
    element_focus.cli_main()
