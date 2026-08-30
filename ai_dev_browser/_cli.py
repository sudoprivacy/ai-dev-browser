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


# Names of the live handle a tab-taking core function receives as its first
# parameter. The CLI injects it and must never expose it as a flag — you cannot
# pass a Tab object through a shell.
#
# Two names are in use: `tab`, and `browser_or_tab` for the tab-management tools
# that also accept a BrowserClient. `tools/_generate.py` reads the same set to
# decide `requires_tab`, which is the point of defining it once: the two used to
# disagree — the generator knew both names, the parser only knew `tab` — so
# `tab_list` / `tab_new` grew a required `--browser-or-tab` flag that no shell
# could satisfy, and were unusable from the CLI.
INJECTED_FIRST_PARAMS = frozenset({"tab", "browser_or_tab"})


def _get_literal_choices(hint) -> list | None:
    """Extract choices from Literal type hint."""
    origin = get_origin(hint)
    if origin is Literal:
        return list(get_args(hint))
    return None


def _unwrap_optional(hint):
    """Unwrap X | None → X for type detection."""
    import types
    from typing import Union

    origin = get_origin(hint)
    union_origins = (Union, getattr(types, "UnionType", ()))
    if origin in union_origins:
        non_none = [a for a in get_args(hint) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return hint


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


def _parse_docstring_failure(docstring: str) -> str | None:
    """Extract the body of the Failure: section from a Google-style docstring.

    Tool authors write failure-path steering once in the docstring's
    `Failure:` section (parallel to `Args:` / `Returns:`). This parser
    extracts it at wrap time; `wrap_core` then auto-injects it as the
    `hint` field on any failure return — SSOT with auto-split across
    `--help` (full docstring, reference surface) and failure `hint`
    (just this section, runtime steering surface).

    Rationale: guidance about "what to do if this tool fails" placed
    only in the docstring reaches the LLM at most via `--help`, which
    is an on-demand call the LLM rarely makes at invocation-failure
    time. Routing the same authored text into the failure return is
    the only channel with 100% reach at the moment the LLM needs to
    recover.

    Returns the flat concatenated hint text, or None if no Failure:
    section is present.
    """
    if not docstring:
        return None

    in_failure = False
    lines: list[str] = []
    for raw in docstring.split("\n"):
        stripped = raw.strip()
        # Google-style section headers are single-word lines ending with ':'
        is_section_header = stripped.endswith(":") and len(stripped.split()) == 1
        if is_section_header:
            if stripped == "Failure:":
                in_failure = True
                continue
            if in_failure:
                break  # next section ends the Failure block
        elif in_failure:
            lines.append(stripped)

    text = " ".join(line for line in lines if line).strip()
    return text or None


def _get_param_type(hint) -> type | Callable:
    """Convert type hint to argparse type."""
    import types
    from typing import Union

    if hint is bool:
        return lambda x: x.lower() in ("true", "1", "yes")
    if hint in (int, float, str):
        return hint
    # For Literal, use str (choices will constrain values)
    if get_origin(hint) is Literal:
        return str
    # list[X] → element type (nargs handled in _generate_parser)
    if get_origin(hint) is list:
        elem_args = get_args(hint)
        return _get_param_type(elem_args[0]) if elem_args else str
    # dict → accept JSON string on CLI
    if hint is dict or get_origin(hint) is dict:
        return json.loads
    # Handle Union types like int | None, str | None.
    # PEP 604 `int | None` has origin types.UnionType; classic
    # `Union[int, None]` has origin typing.Union — accept both.
    origin = get_origin(hint)
    union_origins = (Union, getattr(types, "UnionType", ()))
    if origin in union_origins:
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

    # Connection-scope arguments — which browser, which tab. Injected here for
    # every tab-taking tool rather than declared in 50 core signatures: they
    # select the *target* of a call, they are not parameters of the action.
    if requires_tab:
        parser.add_argument(
            "--port",
            "-p",
            type=int,
            default=None,
            help="Chrome debugging port (auto-detects running Chrome if not specified)",
        )
        parser.add_argument(
            "--tab-url",
            type=str,
            default=None,
            help=(
                "Act on the tab whose URL contains this substring (e.g. ':5173'). "
                "Without it, a browser with several page targets — Electron "
                "windows, a many-tab Chrome — is a guess. Settable process-wide "
                "via AI_DEV_BROWSER_TAB_URL."
            ),
        )
        parser.add_argument(
            "--transport",
            choices=["cdp", "extension"],
            default=None,
            help=(
                "Which browser to drive: 'cdp' (a launched/attached CDP Chrome, "
                "the default) or 'extension' (your REAL browser via the bridge "
                "extension — real profile, logins, device-trust; opt-in, needs "
                "the extension loaded). Settable process-wide via "
                "AI_DEV_BROWSER_TRANSPORT. See `browser_connect`."
            ),
        )

    # Add arguments from function signature (skip the injected handle)
    for name, param in sig.parameters.items():
        if name in INJECTED_FIRST_PARAMS:
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

        # Unwrap Optional for structural detection (list, dict)
        inner_hint = _unwrap_optional(hint)
        inner_origin = get_origin(inner_hint)

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
        elif inner_origin is list:
            # list[str] → nargs='*' so CLI accepts: --flag val1 val2 val3
            elem_args = get_args(inner_hint)
            elem_type = _get_param_type(elem_args[0]) if elem_args else str
            parser.add_argument(
                f"--{name.replace('_', '-')}",
                nargs="*",
                type=elem_type,
                default=param.default if not required else None,
                help=help_text,
            )
        elif inner_origin is dict or inner_hint is dict:
            # dict → accept JSON string on CLI: --flag '{"key": "value"}'
            parser.add_argument(
                f"--{name.replace('_', '-')}",
                type=json.loads,
                default=param.default if not required else None,
                help=help_text,
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
            # Windows defaults stdout to cp1252, which chokes on any non-Latin
            # char (e.g. `→` in docstrings → `--help` raises UnicodeEncodeError).
            # Pin both streams to UTF-8 so help/JSON/log output is encoding-safe
            # regardless of the host console codec.
            for stream in (sys.stdout, sys.stderr):
                reconfigure = getattr(stream, "reconfigure", None)
                if reconfigure is not None:
                    reconfigure(encoding="utf-8")

            # When AI_DEV_BROWSER_REDIRECT is set, block direct access and
            # print the redirect message (controlled by the embedding app).
            redirect = os.environ.get("AI_DEV_BROWSER_REDIRECT")
            if redirect:
                print(redirect, file=sys.stderr)
                sys.exit(1)

            parser = _generate_parser(func, requires_tab=requires_tab)
            args = parser.parse_args()

            if requires_tab:
                # Port resolution (explicit → env → workspace scan → default)
                # lives in connect_browser itself now — CLI and Python API share
                # the same resolution path, no duplication here.
                from ai_dev_browser.core import connect_browser, get_active_tab
                from ai_dev_browser.core.config import resolve_transport

                async def run():
                    try:
                        # Transport is a connection-scope choice (like --port):
                        # cdp attaches to a Chrome; extension drives the user's
                        # real browser via the bridge extension.
                        if (
                            resolve_transport(getattr(args, "transport", None))
                            == "extension"
                        ):
                            from ai_dev_browser.core.connection import connect_extension

                            browser = await connect_extension()
                        else:
                            browser = await connect_browser(port=args.port)
                        # Same tab-selection path for both transports — the
                        # bridge is a real BrowserClient, so get_active_tab /
                        # --tab-url work identically.
                        tab = await get_active_tab(browser, url_contains=args.tab_url)

                        # Connection-scope args select the target, they are not
                        # arguments to the core function — strip before calling.
                        kwargs = {
                            k.replace("-", "_"): v
                            for k, v in vars(args).items()
                            if k not in ("port", "tab_url", "transport")
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

    failure_hint = _parse_docstring_failure(core_func.__doc__ or "")

    @functools.wraps(core_func)
    async def wrapper(*args, **kwargs):
        try:
            result = await core_func(*args, **kwargs)
        except Exception as e:
            # Verbatim message — Python `repr(e)` and CLI stdout stay in
            # lockstep (cli-steering-engineering rule 7: never re-render error text
            # in tool files).
            out: dict = {"error": str(e)}
            if failure_hint:
                out["hint"] = failure_hint
            return out

        if isinstance(result, bool):
            if result:
                return {result_key: True}
            out = {"error": "Operation failed"}
            if failure_hint:
                out["hint"] = failure_hint
            return out
        if isinstance(result, dict):
            filtered = _filter_dict_for_json(result)
            # Auto-inject failure hint when the tool reports failure via
            # result_key=False. Pairs with cli-steering-engineering Rule 5a: failure
            # steering goes through the return channel (100% reach at
            # invocation time), not docstring (only reaches on --help).
            if filtered.get(result_key) is False and failure_hint:
                filtered.setdefault("hint", failure_hint)
            return filtered
        if isinstance(result, list):
            # Pass lists through unwrapped — tools returning catalogs
            # (page_discover, tab_list, ...) stay iterable at the Python
            # API AND the CLI JSON output. Wrapping would turn the list
            # into `{result_key: [...]}`, which forces callers to do
            # `result["elements"]` even though the variable name +
            # function name already say "this is a list". SSOT rule 5:
            # Core returns a JSON-serializable value; CLI outputs it
            # verbatim. The shape can be dict OR list — what matters is
            # Python return == CLI stdout.
            return result
        return {result_key: result}

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

    failure_hint = _parse_docstring_failure(core_func.__doc__ or "")

    @functools.wraps(core_func)
    def wrapper(*args, **kwargs):
        try:
            result = core_func(*args, **kwargs)
        except Exception as e:
            out: dict = {"error": str(e)}
            if failure_hint:
                out["hint"] = failure_hint
            return out

        if isinstance(result, bool):
            if result:
                return {result_key: True}
            out = {"error": "Operation failed"}
            if failure_hint:
                out["hint"] = failure_hint
            return out
        if isinstance(result, dict):
            filtered = _filter_dict_for_json(result)
            if filtered.get(result_key) is False and failure_hint:
                filtered.setdefault("hint", failure_hint)
            return filtered
        if isinstance(result, list):
            return result  # see wrap_core note on list passthrough
        return {result_key: result}

    return wrapper
