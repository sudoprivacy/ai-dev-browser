"""Execute JavaScript in the page."""

import json

from .._cli import as_cli


@as_cli()
async def page_eval(tab, js: str) -> dict:
    """Execute JavaScript in the page.

    Args:
        tab: Browser tab
        js: JavaScript code to execute
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
        return {"error": f"page_eval failed: {e}"}


if __name__ == "__main__":
    page_eval.cli_main()
