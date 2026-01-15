#!/usr/bin/env python3
"""Send raw CDP (Chrome DevTools Protocol) commands.

Usage:
    python tools/cdp_send.py --method "Page.captureScreenshot"
    python tools/cdp_send.py --method "Network.getCookies" --params '{"urls": ["https://example.com"]}'
    python tools/cdp_send.py --method "Runtime.evaluate" --params '{"expression": "1+1"}'

Output:
    {"result": {...}}

Reference: https://chromedevtools.github.io/devtools-protocol/
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._common import output, error, add_port_arg, connect_browser, get_active_tab, run_async


async def main_async(args):
    browser = await connect_browser(args.port)
    tab = await get_active_tab(browser)

    # Parse method into domain and command
    if "." not in args.method:
        error("Method must be in format 'Domain.command' (e.g., 'Page.captureScreenshot')")

    domain, command = args.method.split(".", 1)

    # Parse params
    params = {}
    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as e:
            error(f"Invalid JSON params: {e}")

    try:
        # Import CDP module dynamically
        import nodriver.cdp as cdp

        # Get the domain module
        domain_module = getattr(cdp, domain.lower(), None)
        if not domain_module:
            error(f"Unknown CDP domain: {domain}")

        # Get the command function
        command_func = getattr(domain_module, command, None)
        if not command_func:
            error(f"Unknown CDP command: {domain}.{command}")

        # Call the command
        result = await tab.send(command_func(**params))

        # Convert result to dict if possible
        if hasattr(result, "__dict__"):
            result_dict = {k: v for k, v in result.__dict__.items() if not k.startswith("_")}
        elif hasattr(result, "_asdict"):
            result_dict = result._asdict()
        else:
            result_dict = result

        output({
            "method": args.method,
            "result": result_dict
        })

    except Exception as e:
        error(f"CDP command failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Send CDP command")
    add_port_arg(parser)
    parser.add_argument("--method", "-m", required=True, help="CDP method (e.g., 'Page.captureScreenshot')")
    parser.add_argument("--params", help="JSON params for the method")
    args = parser.parse_args()

    run_async(main_async(args))


if __name__ == "__main__":
    main()
