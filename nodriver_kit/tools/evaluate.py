"""Execute JavaScript in the page.

CLI:
    python -m nodriver_kit.tools.evaluate --js "document.title"
    python -m nodriver_kit.tools.evaluate --js "window.scrollTo(0, 100)"

Python:
    from nodriver_kit.tools import evaluate
    result = await evaluate(tab, js="document.title")
"""

import json
from ._cli import as_cli


@as_cli
async def evaluate(tab, js: str) -> dict:
    """Execute JavaScript in the page.

    Args:
        tab: Browser tab
        js: JavaScript code to execute

    Returns:
        {"result": ...} with the JS return value
    """
    try:
        result = await tab.evaluate(js)
        # Try to serialize result
        try:
            json.dumps(result)
            return {"result": result}
        except (TypeError, ValueError):
            return {"result": str(result)}
    except Exception as e:
        return {"error": f"Evaluate failed: {e}"}


if __name__ == "__main__":
    evaluate.cli_main()
