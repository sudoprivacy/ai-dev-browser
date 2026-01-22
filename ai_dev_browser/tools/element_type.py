"""Type text into an element.

CLI:
    python -m ai_dev_browser.tools.element_type --selector "input.email" --text "user@example.com"

Python:
    from ai_dev_browser.tools import element_type
    result = await element_type(tab, selector="input.email", text="user@example.com")
"""

from ai_dev_browser.core import type_text as core_type_text
from ._cli import as_cli


@as_cli()
async def element_type(tab, text: str, selector: str = None, clear: bool = False) -> dict:
    """Type text into an element.

    Args:
        tab: Browser tab
        text: Text to type
        selector: CSS selector of input element
        clear: If True, clear existing content first

    Returns:
        {"typed": True} on success
    """
    if not selector:
        return {"error": "Must specify --selector"}

    try:
        success = await core_type_text(tab, text=text, selector=selector, clear=clear)
        if success:
            return {"typed": True, "text": text}
        else:
            return {"error": "Element not found"}
    except Exception as e:
        return {"error": f"element_type failed: {e}"}


if __name__ == "__main__":
    element_type.cli_main()
