"""CLI decorator for tools.

Makes functions usable as both Python imports and CLI commands.

Usage:
    # Tool that operates on existing browser (requires tab)
    @as_cli()
    async def click(tab, selector: str, text: str = None) -> dict:
        '''Click an element.'''
        ...

    # Tool that manages browser lifecycle (no tab needed)
    @as_cli(requires_tab=False)
    def browser_start(port: int = None, headless: bool = False) -> dict:
        '''Start a browser.'''
        ...

    # As CLI: python -m ai_dev_browser.tools.click --selector "button"
    # As Python: from ai_dev_browser.tools import click; await click(tab, "button")
"""

import argparse
import asyncio
import functools
import inspect
import json
import os
import sys
from collections.abc import Callable
from typing import Any, Literal, get_args, get_origin, get_type_hints


def _get_literal_choices(hint) -> list | None:
    """Extract choices from Literal type hint."""
    origin = get_origin(hint)
    if origin is Literal:
        return list(get_args(hint))
    return None


def _parse_docstring_args(docstring: str) -> dict[str, str]:
    """Extract arg descriptions from docstring Args section.

    Parses Google-style docstrings:
        Args:
            param_name: Description here
            another_param: Another description
    """
    if not docstring:
        return {}

    args_section = {}
    in_args = False
    current_arg = None
    current_desc = []

    for line in docstring.split("\n"):
        stripped = line.strip()

        if stripped == "Args:":
            in_args = True
            continue
        elif (
            in_args
            and stripped
            and not stripped[0].isspace()
            and stripped.endswith(":")
        ):
            # New section like "Returns:" or "Raises:"
            if current_arg:
                args_section[current_arg] = " ".join(current_desc).strip()
            break
        elif in_args:
            # Check if this is a new arg definition (name: description)
            if ": " in stripped:
                if current_arg:
                    args_section[current_arg] = " ".join(current_desc).strip()
                parts = stripped.split(": ", 1)
                current_arg = parts[0].strip()
                current_desc = [parts[1].strip()] if len(parts) > 1 else []
            elif current_arg and stripped:
                # Continuation of previous arg description
                current_desc.append(stripped)

    if current_arg:
        args_section[current_arg] = " ".join(current_desc).strip()

    return args_section


def _get_param_type(hint) -> type | Callable[[str], bool]:
    """Convert type hint to argparse type."""
    from typing import Union

    if hint is bool:
        return lambda x: x.lower() in ("true", "1", "yes")
    if hint in (int, float, str):
        return hint
    # For Literal, use str (choices will constrain values)
    if get_origin(hint) is Literal:
        return str
    # Handle Union types like int | None, str | None
    # Extract the non-None type from the union
    origin = get_origin(hint)
    if origin is Union:
        args = get_args(hint)
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            return _get_param_type(non_none_args[0])
    return str


def _generate_parser(
    func: Callable,
    requires_tab: bool = True,
    description: str = None,
) -> argparse.ArgumentParser:
    """Generate argparse parser from function signature."""
    sig = inspect.signature(func)
    hints = get_type_hints(func) if hasattr(func, "__annotations__") else {}
    arg_descriptions = _parse_docstring_args(func.__doc__ or "")

    parser = argparse.ArgumentParser(
        description=description or func.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Add --port for browser connection (only when requires_tab)
    if requires_tab:
        parser.add_argument(
            "--port",
            "-p",
            type=int,
            default=None,
            help="Chrome debugging port (auto-detects running Chrome if not specified)",
        )

    # Add arguments from function signature (skip 'tab' parameter)
    for name, param in sig.parameters.items():
        if name == "tab":
            continue

        hint = hints.get(name, str)
        param_type = _get_param_type(hint)
        required = param.default is inspect.Parameter.empty

        # Get help text from docstring Args section, fallback to type hint
        help_text = arg_descriptions.get(name)
        if not help_text:
            if hasattr(hint, "__name__"):
                help_text = f"({hint.__name__})"
            elif hasattr(hint, "__origin__"):
                help_text = f"({str(hint)})"
            else:
                help_text = "(str)"

        if hint is bool:
            # For bool, use intuitive flag names:
            # - default False: --flag to enable (store_true)
            # - default True: --no-flag to disable (store_false)
            if param.default is False or param.default is inspect.Parameter.empty:
                parser.add_argument(
                    f"--{name.replace('_', '-')}",
                    action="store_true",
                    default=False,
                    help=help_text,
                )
            else:
                # Default is True, use --no-xxx to disable
                parser.add_argument(
                    f"--no-{name.replace('_', '-')}",
                    dest=name.replace("-", "_"),
                    action="store_false",
                    default=True,
                    help=f"Disable: {help_text}",
                )
        else:
            kwargs: dict[str, Any] = {
                "type": param_type,
                "help": help_text,
            }
            if not required:
                kwargs["default"] = param.default

            # Handle Literal types with choices
            choices = _get_literal_choices(hint)
            if choices:
                kwargs["choices"] = choices
                kwargs["help"] = f"One of: {', '.join(str(c) for c in choices)}"

            parser.add_argument(
                f"--{name.replace('_', '-')}",
                required=required,
                **kwargs,  # type: ignore[arg-type]
            )

    return parser


def as_cli(requires_tab: bool = True):
    """Decorator that adds CLI capability to a function.

    Args:
        requires_tab: If True (default), the function requires a browser tab.
                     CLI will auto-connect to browser and pass tab as first arg.
                     If False, the function manages browser lifecycle itself.

    The decorated function can be:
    1. Imported and called directly: await func(tab, ...) or func(...)
    2. Run as CLI: python -m module --arg value

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        is_async = asyncio.iscoroutinefunction(func)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        wrapper = async_wrapper if is_async else sync_wrapper

        def cli_main():
            """Entry point for CLI usage."""
            # When AI_DEV_BROWSER_REDIRECT is set, block direct access and
            # print the redirect message (controlled by the embedding app).
            redirect = os.environ.get("AI_DEV_BROWSER_REDIRECT")
            if redirect:
                print(redirect, file=sys.stderr)
                sys.exit(1)

            parser = _generate_parser(func, requires_tab=requires_tab)
            args = parser.parse_args()

            if requires_tab:
                # Connect to browser and get tab
                from ai_dev_browser.core import connect_browser, get_active_tab

                async def run():
                    try:
                        port = args.port
                        if port is None:
                            # Check env var first (set by embedding apps like Sudowork)
                            env_port = os.environ.get("AI_DEV_BROWSER_PORT")
                            if env_port:
                                port = int(env_port)
                            else:
                                # Auto-detect: page_find a running ai-dev-browser Chrome
                                from ai_dev_browser.core.port import find_debug_chromes
                                from ai_dev_browser.core.port import is_chrome_in_use

                                for candidate, _pid in find_debug_chromes():
                                    if not is_chrome_in_use(candidate):
                                        port = candidate
                                        break

                            if port is None:
                                print(
                                    json.dumps(
                                        {
                                            "error": "No available Chrome found. "
                                            "Run browser-start first, or specify --port."
                                        },
                                        ensure_ascii=False,
                                        indent=2,
                                    )
                                )
                                sys.exit(1)

                        browser = await connect_browser(port=port)
                        tab = await get_active_tab(browser)

                        # Build kwargs from args, excluding 'port'
                        kwargs = {
                            k.replace("-", "_"): v
                            for k, v in vars(args).items()
                            if k != "port"
                        }

                        result = await func(tab, **kwargs)
                        print(json.dumps(result, ensure_ascii=False, indent=2))

                    except Exception as e:
                        print(
                            json.dumps({"error": str(e)}, ensure_ascii=False, indent=2)
                        )
                        sys.exit(1)

                asyncio.run(run())
            else:
                # No browser connection needed
                try:
                    kwargs = {k.replace("-", "_"): v for k, v in vars(args).items()}

                    result = asyncio.run(func(**kwargs)) if is_async else func(**kwargs)

                    print(json.dumps(result, ensure_ascii=False, indent=2))

                except Exception as e:
                    print(json.dumps({"error": str(e)}, ensure_ascii=False, indent=2))
                    sys.exit(1)

        # Attach CLI runner to the function
        wrapper.cli_main = cli_main  # type: ignore[attr-defined]
        wrapper.__wrapped__ = func  # type: ignore[attr-defined]

        return wrapper

    return decorator


def output(data: dict) -> None:
    """Output JSON to stdout."""
    print(json.dumps(data, ensure_ascii=False, indent=2))


def error(message: str, code: int = 1) -> None:
    """Output error and exit."""
    output({"error": message})
    sys.exit(code)


def _json_serializable(obj: Any) -> bool:
    """Check if object is JSON serializable."""
    try:
        json.dumps(obj)
        return True
    except (TypeError, ValueError):
        return False


def _filter_dict_for_json(d: dict) -> dict:
    """Filter dict to only JSON-serializable values."""
    return {k: v for k, v in d.items() if _json_serializable(v)}


def wrap_core(core_func: Callable, result_key: str = "success") -> Callable:
    """Wrap an async core function for CLI use, preserving its signature (SSOT).

    This enables true SSOT: parameters are defined once in core function,
    CLI automatically inherits them.

    Non-JSON-serializable values (like Tab objects) are automatically filtered
    from the output. Core functions can return them for programmatic use,
    but CLI will only show serializable values.

    Args:
        core_func: The async core function to wrap
        result_key: Key name for successful result (e.g., "clicked", "typed")

    Returns:
        Wrapped function with same signature, JSON-formatted output

    Example:
        # element_click.py - True SSOT
        from ai_dev_browser.core import click
        from .._cli import as_cli, wrap_core

        element_click = as_cli()(wrap_core(click, "clicked"))
    """

    @functools.wraps(core_func)
    async def wrapper(*args, **kwargs):
        try:
            result = await core_func(*args, **kwargs)
            if isinstance(result, bool):
                if result:
                    return {result_key: True}
                else:
                    return {"error": "Operation failed"}
            elif isinstance(result, dict):
                # Filter out non-serializable values for CLI output
                return _filter_dict_for_json(result)
            else:
                return {result_key: result}
        except Exception as e:
            return {"error": f"{core_func.__name__} failed: {e}"}

    return wrapper


def wrap_core_sync(core_func: Callable, result_key: str = "success") -> Callable:
    """Wrap a sync core function for CLI use, preserving its signature (SSOT).

    Same as wrap_core but for synchronous functions.

    Args:
        core_func: The sync core function to wrap
        result_key: Key name for successful result

    Returns:
        Wrapped sync function with same signature, JSON-formatted output

    Example:
        # browser_start.py - True SSOT
        from ai_dev_browser.core import browser_start
        from .._cli import as_cli, wrap_core_sync

        browser_start = as_cli(requires_tab=False)(wrap_core_sync(browser_start, "port"))
    """

    @functools.wraps(core_func)
    def wrapper(*args, **kwargs):
        try:
            result = core_func(*args, **kwargs)
            if isinstance(result, bool):
                if result:
                    return {result_key: True}
                else:
                    return {"error": "Operation failed"}
            elif isinstance(result, dict):
                # Filter out non-serializable values for CLI output
                return _filter_dict_for_json(result)
            else:
                return {result_key: result}
        except Exception as e:
            return {"error": f"{core_func.__name__} failed: {e}"}

    return wrapper
