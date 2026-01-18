"""Send CDP command.

CLI:
    python -m nodriver_kit.tools.cdp_send --method "Page.captureScreenshot"
    python -m nodriver_kit.tools.cdp_send --method "DOM.getDocument" --params '{"depth": 1}'

Python:
    from nodriver_kit.tools import cdp_send
    result = await cdp_send(tab, method="Page.captureScreenshot")
"""

import json as json_module
from ._cli import as_cli


@as_cli
async def cdp_send(tab, method: str, params: str = None) -> dict:
    """Send a CDP (Chrome DevTools Protocol) command.

    Args:
        tab: Browser tab
        method: CDP method name (e.g., "Page.captureScreenshot")
        params: JSON string of parameters

    Returns:
        CDP response
    """
    try:
        # Parse params if provided
        parsed_params = {}
        if params:
            parsed_params = json_module.loads(params)

        # Send CDP command
        result = await tab.send(method, **parsed_params)

        # Try to serialize result
        try:
            json_module.dumps(result)
            return {"result": result}
        except (TypeError, ValueError):
            return {"result": str(result)}
    except Exception as e:
        return {"error": f"CDP command failed: {e}"}


if __name__ == "__main__":
    cdp_send.cli_main()
