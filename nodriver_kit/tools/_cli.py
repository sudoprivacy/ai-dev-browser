"""CLI decorator for actions.

Makes async functions usable as both Python imports and CLI commands.

Usage:
    @as_cli
    async def click(tab, selector: str, text: str = None) -> dict:
        '''Click an element.'''
        ...

    # As CLI: python -m nodriver_kit.tools.click --selector "button"
    # As Python: from nodriver_kit.tools import click; await click(tab, "button")
"""

import argparse
import asyncio
import functools
import inspect
import json
import sys
from typing import Any, Callable, get_type_hints


def _get_param_type(hint) -> type:
    """Convert type hint to argparse type."""
    if hint is bool:
        return lambda x: x.lower() in ("true", "1", "yes")
    if hint in (int, float, str):
        return hint
    return str


def _generate_parser(func: Callable, description: str = None) -> argparse.ArgumentParser:
    """Generate argparse parser from function signature."""
    sig = inspect.signature(func)
    hints = get_type_hints(func) if hasattr(func, "__annotations__") else {}

    parser = argparse.ArgumentParser(
        description=description or func.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Add --port for browser connection
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=9222,
        help="Chrome debugging port (default: 9222)",
    )

    # Add arguments from function signature (skip 'tab' parameter)
    for name, param in sig.parameters.items():
        if name == "tab":
            continue

        hint = hints.get(name, str)
        param_type = _get_param_type(hint)
        required = param.default is inspect.Parameter.empty

        kwargs = {
            "type": param_type,
            "help": f"({hint.__name__ if hasattr(hint, '__name__') else 'str'})",
        }

        if not required:
            kwargs["default"] = param.default

        if hint is bool:
            # For bool, use store_true action
            parser.add_argument(
                f"--{name.replace('_', '-')}",
                action="store_true" if param.default is False else "store_false",
                help=kwargs["help"],
            )
        else:
            parser.add_argument(
                f"--{name.replace('_', '-')}",
                required=required,
                **kwargs,
            )

    return parser


def as_cli(func: Callable) -> Callable:
    """Decorator that adds CLI capability to an async function.

    The decorated function can be:
    1. Imported and called directly: await func(tab, ...)
    2. Run as CLI: python -m module --arg value

    The function must:
    - Be async
    - Take 'tab' as first parameter
    - Return a dict (will be JSON-serialized for CLI output)
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await func(*args, **kwargs)

    def cli_main():
        """Entry point for CLI usage."""
        from nodriver_kit.core import connect_browser, get_active_tab

        parser = _generate_parser(func)
        args = parser.parse_args()

        async def run():
            try:
                browser = await connect_browser(port=args.port)
                tab = await get_active_tab(browser)

                # Build kwargs from args, excluding 'port'
                kwargs = {
                    k.replace("-", "_"): v
                    for k, v in vars(args).items()
                    if k != "port"
                }

                result = await func(tab, **kwargs)

                # Output as JSON
                print(json.dumps(result, ensure_ascii=False, indent=2))

            except Exception as e:
                print(json.dumps({"error": str(e)}, ensure_ascii=False, indent=2))
                sys.exit(1)

        asyncio.run(run())

    # Attach CLI runner to the function
    wrapper.cli_main = cli_main
    wrapper.__wrapped__ = func

    return wrapper


def output(data: dict) -> None:
    """Output JSON to stdout."""
    print(json.dumps(data, ensure_ascii=False, indent=2))


def error(message: str, code: int = 1) -> None:
    """Output error and exit."""
    output({"error": message})
    sys.exit(code)
