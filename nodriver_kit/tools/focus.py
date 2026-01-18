"""Focus an element on the page.

CLI:
    python -m nodriver_kit.tools.focus --selector "input[name='email']"
    python -m nodriver_kit.tools.focus --text "Email"

Python:
    from nodriver_kit.tools import focus
    result = await focus(tab, selector="input[name='email']")
"""

from nodriver_kit.core import find_element
from ._cli import as_cli


@as_cli
async def focus(tab, selector: str = None, text: str = None) -> dict:
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
        return {"error": f"Focus failed: {e}"}


if __name__ == "__main__":
    focus.cli_main()
