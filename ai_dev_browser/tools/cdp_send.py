"""Send CDP command.

CLI:
    python -m ai_dev_browser.tools.cdp_send --method "Browser.getVersion"
    python -m ai_dev_browser.tools.cdp_send --method "DOM.getDocument" --params '{"depth": 1}'

Python:
    from ai_dev_browser.tools import cdp_send
    result = await cdp_send(tab, method="Browser.getVersion")
"""

import json as json_module
import re
import nodriver.cdp as cdp
from ._cli import as_cli


def _camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case."""
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()


def _get_cdp_command(method: str, params: dict):
    """Dynamically create a CDP command generator.

    Args:
        method: CDP method like "Browser.getVersion" or "DOM.getDocument"
        params: Parameters dict

    Returns:
        CDP command generator
    """
    domain, cmd = method.split('.')
    domain_snake = _camel_to_snake(domain)
    cmd_snake = _camel_to_snake(cmd)

    # Get the domain module (e.g., cdp.browser)
    domain_module = getattr(cdp, domain_snake)

    # Get the command function (e.g., cdp.browser.get_version)
    cmd_func = getattr(domain_module, cmd_snake)

    # Call with params
    return cmd_func(**params) if params else cmd_func()


@as_cli()
async def cdp_send(tab, method: str, params: str = None) -> dict:
    """Send a CDP (Chrome DevTools Protocol) command.

    Args:
        tab: Browser tab
        method: CDP method name (e.g., "Browser.getVersion", "DOM.getDocument")
        params: JSON string of parameters

    Returns:
        CDP response
    """
    try:
        # Parse params if provided
        parsed_params = {}
        if params:
            parsed_params = json_module.loads(params)

        # Create CDP command generator
        cdp_cmd = _get_cdp_command(method, parsed_params)

        # Send CDP command
        result = await tab.send(cdp_cmd)

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
