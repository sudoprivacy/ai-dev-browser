"""CDP (Chrome DevTools Protocol) command operations."""

import json

from ai_dev_browser import cdp as cdp_module

from ._case import camel_to_snake
from ._tab import Tab


def _get_cdp_command(method: str, params: dict):
    """Dynamically create a CDP command generator.

    Args:
        method: CDP method like "Browser.getVersion" or "DOM.getDocument"
        params: Parameters dict

    Returns:
        CDP command generator
    """
    domain, cmd = method.split(".")
    domain_snake = camel_to_snake(domain)
    cmd_snake = camel_to_snake(cmd)

    # Get the domain module (e.g., cdp.browser)
    domain_mod = getattr(cdp_module, domain_snake)

    # Get the command function (e.g., cdp.browser.get_version)
    cmd_func = getattr(domain_mod, cmd_snake)

    # Call with params
    return cmd_func(**params) if params else cmd_func()


async def cdp_send(
    tab: Tab,
    method: str,
    params: str | None = None,
) -> dict:
    """Send a CDP (Chrome DevTools Protocol) command.

    Args:
        tab: Tab instance
        method: CDP method name (e.g., "Browser.getVersion", "DOM.getDocument")
        params: JSON string of parameters. Keys may be the CDP-native camelCase
            copied straight from the protocol docs (`deviceScaleFactor`) or the
            snake_case the Python bindings use (`device_scale_factor`) — both
            are accepted.

    Returns:
        dict with result or error
    """
    # Parse params if provided
    parsed_params = {}
    if params:
        parsed_params = json.loads(params)

    # The CDP docs (and everyone copying from them) use camelCase; the vendored
    # bindings take snake_case kwargs. Normalize top-level keys so a verbatim
    # `{"deviceScaleFactor": 1}` doesn't blow up as an unexpected-kwarg error.
    parsed_params = {camel_to_snake(k): v for k, v in parsed_params.items()}

    # Create CDP command generator
    cdp_cmd = _get_cdp_command(method, parsed_params)

    # Send CDP command
    result = await tab.send(cdp_cmd)

    # Try to serialize result
    try:
        json.dumps(result)
        return {"result": result}
    except (TypeError, ValueError):
        return {"result": str(result)}
