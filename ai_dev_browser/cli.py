"""Umbrella ``browser`` CLI — agent-friendly noun-then-verb front end.

This module wraps the ~50 auto-generated tools in
``ai_dev_browser.tools`` under a single ``browser`` console command:

    browser <noun> <verb> [flags]

It is purely additive. The per-tool modules
(``python -m ai_dev_browser.tools.page_goto``) and the
``ai_dev_browser.core`` Python API are untouched. Discovery, the
INTERNAL exclusion set, ``requires_tab`` detection and ``result_key``
metadata are all reused from ``ai_dev_browser.tools._generate`` so the
command tree stays in sync with core automatically.

Design follows the harness-playbook for agent-facing CLIs:
  - noun-then-verb subcommands grouped by resource
  - terse default output, ``--full`` for everything
  - ``--json`` / ``--quiet`` / ``--no-interactive`` on every command,
    auto-enabled when stdout is not a TTY
  - data on stdout, errors on stderr; in ``--json`` mode errors are
    ``{"error": {code, message, retryable, hint}}``
  - distinct non-zero exit codes per error category
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable
from typing import Any

from ._cli import _generate_parser
from .tools._generate import _discover_tools

# ---------------------------------------------------------------------------
# Exit codes (harness-playbook rule 4). Never return 1 for everything.
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_VALIDATION = 2  # bad / missing args
EXIT_NOT_FOUND = 4  # element / browser / target not found
EXIT_CONFLICT = 5  # already exists / state conflict
EXIT_AUTH = 7  # authentication required
EXIT_RATE_LIMIT = 8  # rate limited
EXIT_TRANSIENT = 9  # timeout / connection / retryable

# ---------------------------------------------------------------------------
# Noun-then-verb grouping.
#
# We derive the (noun, verb) for every discovered tool from its function
# name so the tree stays in sync with core. A small override table handles
# the handful of names whose prefix/suffix doesn't cleanly split into
# resource + action.
# ---------------------------------------------------------------------------

# Explicit (noun, verb) overrides keyed by core function name.
_GROUP_OVERRIDES: dict[str, tuple[str, str]] = {
    # browser_* lifecycle reads more naturally as a "session" resource
    "browser_start": ("session", "start"),
    "browser_stop": ("session", "stop"),
    "browser_list": ("session", "list"),
    # *_by_ref element interactions → element <verb>
    "focus_by_ref": ("element", "focus"),
    "hover_by_ref": ("element", "hover"),
    "highlight_by_ref": ("element", "highlight"),
    "html_by_ref": ("element", "html"),
    "screenshot_by_ref": ("element", "screenshot"),
    "select_by_ref": ("element", "select"),
    "upload_by_ref": ("element", "upload"),
    "drag_by_ref": ("element", "drag"),
    "click_by_ref": ("click", "ref"),
    "type_by_ref": ("type", "ref"),
    # single-tool resources whose name has no separator
    "js_evaluate": ("js", "evaluate"),
    "cdp_send": ("cdp", "send"),
    "dialog_respond": ("dialog", "respond"),
    "window_set": ("window", "set"),
    "login_interactive": ("login", "interactive"),
    # download is a lone verb-less tool → expose as `browser download run`
    "download": ("download", "run"),
}

# Prefix → noun for the regular ``<prefix>_<rest>`` tools. The verb is the
# remainder with underscores turned into dashes.
_PREFIX_NOUNS: dict[str, str] = {
    "page": "page",
    "tab": "tab",
    "mouse": "mouse",
    "cookies": "cookies",
    "storage": "storage",
    "click_by": "click",
    "find_by": "find",
    "type_by": "type",
}


def _derive_group(name: str) -> tuple[str, str]:
    """Map a core function name to ``(noun, verb)``.

    Override table wins; otherwise split on the longest matching prefix
    and dash-ify the remainder.
    """
    if name in _GROUP_OVERRIDES:
        return _GROUP_OVERRIDES[name]
    # Try two-token prefixes first (click_by, find_by, type_by), then one.
    for prefix in ("click_by", "find_by", "type_by"):
        if name.startswith(prefix + "_"):
            verb = name[len(prefix) + 1 :].replace("_", "-")
            return _PREFIX_NOUNS[prefix], verb
    head, sep, rest = name.partition("_")
    if sep and head in _PREFIX_NOUNS:
        return _PREFIX_NOUNS[head], rest.replace("_", "-")
    # Fallback: whole name is the noun, verb "run".
    return name.replace("_", "-"), "run"


def _build_tree() -> dict[str, dict[str, dict[str, Any]]]:
    """Build ``{noun: {verb: tool_meta}}`` from discovery.

    ``tool_meta`` carries everything the dispatcher needs: the resolved
    core callable, requires_tab, result_key, is_async, and the original
    core function name.
    """
    import ai_dev_browser.core as core_module

    tree: dict[str, dict[str, dict[str, Any]]] = {}
    for tool in _discover_tools():
        name = tool["name"]
        noun, verb = _derive_group(name)
        func = getattr(core_module, name)
        meta = {
            "func": func,
            "name": name,
            "requires_tab": tool["requires_tab"],
            "result_key": tool["result_key"],
            "is_async": tool["is_async"],
            "noun": noun,
            "verb": verb,
        }
        bucket = tree.setdefault(noun, {})
        if verb in bucket:  # pragma: no cover - guards against grouping clashes
            raise RuntimeError(
                f"command clash: {noun} {verb} maps to both "
                f"{bucket[verb]['name']} and {name}"
            )
        bucket[verb] = meta
    return tree


# ---------------------------------------------------------------------------
# Error classification → exit code.
# ---------------------------------------------------------------------------
def _classify(message: str) -> tuple[int, bool, str]:
    """Map an error message to (exit_code, retryable, hint).

    Heuristic: core functions surface plain exceptions / verbatim
    strings, so we pattern-match on the message text. Conservative —
    unknown errors fall through to transient (retryable).
    """
    m = message.lower()
    if any(s in m for s in ("not found", "no such", "no element", "no matching")):
        return EXIT_NOT_FOUND, False, "Check the target exists / re-run discovery."
    if any(
        s in m
        for s in (
            "failed to connect",
            "connection",
            "no browser",
            "refused",
            "no chrome",
        )
    ):
        return (
            EXIT_NOT_FOUND,
            True,
            "Start a browser first: `browser session start`.",
        )
    if "timeout" in m or "timed out" in m:
        return EXIT_TRANSIENT, True, "Increase --timeout or retry."
    if any(s in m for s in ("auth", "unauthorized", "forbidden", "login")):
        return EXIT_AUTH, False, "Authenticate, then retry."
    if "rate limit" in m or "too many" in m:
        return EXIT_RATE_LIMIT, True, "Back off and retry."
    if any(s in m for s in ("already", "in use", "conflict", "exists")):
        return EXIT_CONFLICT, False, "Target already in the desired state."
    if any(
        s in m
        for s in ("invalid", "required", "missing", "must be", "expected", "argument")
    ):
        return EXIT_VALIDATION, False, "Check the command flags."
    return EXIT_TRANSIENT, True, "Unexpected error; retry may help."


# ---------------------------------------------------------------------------
# Output helpers (data→stdout, errors→stderr).
# ---------------------------------------------------------------------------
def _emit_data(data: Any, *, as_json: bool, quiet: bool, full: bool) -> None:
    """Print a successful result to stdout."""
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if quiet:
        # quiet, non-json: print the single most useful scalar, else nothing
        scalar = _primary_scalar(data)
        if scalar is not None:
            print(scalar)
        return
    print(_render_human(data, full=full))


def _emit_error(
    message: str, *, as_json: bool, code: int, retryable: bool, hint: str
) -> int:
    """Print an error to stderr in the agreed shape; return the exit code."""
    if as_json:
        payload = {
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "hint": hint,
            }
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
    else:
        print(f"error: {message}", file=sys.stderr)
        if hint:
            print(f"hint: {hint}", file=sys.stderr)
    return code


def _primary_scalar(data: Any) -> Any:
    """Pick a single representative scalar for --quiet output."""
    if isinstance(data, dict):
        for key in ("port", "url", "path", "value", "result", "count", "tab_id"):
            if key in data and not isinstance(data[key], (dict, list)):
                return data[key]
        for v in data.values():
            if not isinstance(v, (dict, list)):
                return v
    elif isinstance(data, (str, int, float, bool)):
        return data
    elif isinstance(data, list):
        return len(data)
    return None


def _render_human(data: Any, *, full: bool) -> str:
    """Terse human rendering (harness-playbook rule 1: < ~200 tokens).

    Lists show 3-4 key fields per item; dicts show key fields. ``full``
    dumps everything as pretty JSON.
    """
    if full:
        return json.dumps(data, ensure_ascii=False, indent=2)
    if isinstance(data, list):
        if not data:
            return "(0 items)"
        lines = [f"({len(data)} items)"]
        for item in data[:50]:
            lines.append("  " + _summarize_item(item))
        if len(data) > 50:
            lines.append(f"  ... and {len(data) - 50} more (use --full)")
        return "\n".join(lines)
    if isinstance(data, dict):
        return _summarize_item(data)
    return str(data)


def _summarize_item(item: Any) -> str:
    """One-line summary picking up to 4 informative fields."""
    if not isinstance(item, dict):
        return str(item)
    preferred = [
        "port",
        "url",
        "title",
        "tab_id",
        "id",
        "ref",
        "name",
        "text",
        "path",
        "value",
        "count",
        "role",
    ]
    parts: list[str] = []
    for key in preferred:
        if key in item and not isinstance(item[key], (dict, list)):
            val = item[key]
            if isinstance(val, str) and len(val) > 60:
                val = val[:57] + "..."
            parts.append(f"{key}={val}")
        if len(parts) >= 4:
            break
    if not parts:
        # no preferred keys; show first few scalar fields
        for key, val in item.items():
            if not isinstance(val, (dict, list)):
                parts.append(f"{key}={val}")
            if len(parts) >= 4:
                break
    return " ".join(parts) if parts else json.dumps(item, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Per-tool argparse construction (reuses _cli._generate_parser).
# ---------------------------------------------------------------------------
_COMMON_FLAGS = ("json", "quiet", "no_interactive", "full")


def _populate_leaf(parser: argparse.ArgumentParser, meta: dict[str, Any]) -> None:
    """Add signature-derived args + common flags onto a leaf subparser.

    Reuses ``_cli._generate_parser`` for the signature→argparse work
    (port, type coercion, Literal choices, bool flags, list/dict
    handling, docstring help) by copying its generated actions onto
    ``parser``. Then layers the four common agent flags on top.
    """
    func = meta["func"]
    base = _generate_parser(
        func, requires_tab=meta["requires_tab"], description=func.__doc__
    )
    # _generate_parser only skips a parameter literally named ``tab``. Tools
    # whose injected first param is ``browser_or_tab`` (the four tab_* tools)
    # would otherwise expose a bogus required ``--browser-or-tab`` flag. We
    # supply the tab positionally at call time, so drop that flag here.
    skip_dests = {"browser_or_tab"} if meta["requires_tab"] else set()
    for action in base._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if action.dest in skip_dests:
            continue
        # Re-add each generated option onto our subparser. We reconstruct
        # add_argument kwargs from the action object so behavior is identical
        # to the per-tool modules.
        kwargs: dict[str, Any] = {"help": action.help, "dest": action.dest}
        if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
            kwargs["action"] = (
                "store_true"
                if isinstance(action, argparse._StoreTrueAction)
                else "store_false"
            )
            kwargs["default"] = action.default
            kwargs.pop("dest", None)  # store_true/false keep their own dest already
            parser.add_argument(*action.option_strings, dest=action.dest, **kwargs)
            continue
        if action.type is not None:
            kwargs["type"] = action.type
        if action.choices is not None:
            kwargs["choices"] = action.choices
        if action.nargs is not None:
            kwargs["nargs"] = action.nargs
        kwargs["default"] = action.default
        if action.required:
            kwargs["required"] = True
        parser.add_argument(*action.option_strings, **kwargs)

    _add_common_flags(parser)


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    """Attach --json/--quiet/--no-interactive/--full (rule 2)."""
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        dest="json",
        help="Emit machine-readable JSON (auto-on when stdout is not a TTY)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        dest="quiet",
        help="Print only the primary scalar value, suppress chrome",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        default=False,
        dest="no_interactive",
        help="Never prompt; missing required values error out instead of hanging",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        default=False,
        dest="full",
        help="Verbose output: dump all fields",
    )


# ---------------------------------------------------------------------------
# Dispatch / execution.
# ---------------------------------------------------------------------------
def _run_tool(meta: dict[str, Any], ns: argparse.Namespace) -> int:
    """Execute one resolved tool with parsed args; return an exit code."""
    func = meta["func"]
    result_key = meta["result_key"]
    requires_tab = meta["requires_tab"]
    is_async = meta["is_async"]

    # Resolve output mode. Non-TTY → force json + quiet + no-interactive (rule 2/9).
    non_tty = not sys.stdout.isatty()
    as_json = ns.json or non_tty
    quiet = ns.quiet or non_tty
    no_interactive = ns.no_interactive or non_tty
    full = ns.full

    # login_interactive is inherently human-in-the-loop. Fail fast under
    # --no-interactive rather than hang (rule 7).
    if meta["name"] == "login_interactive" and no_interactive:
        return _emit_error(
            "login interactive requires a human; refusing under --no-interactive",
            as_json=as_json,
            code=EXIT_AUTH,
            retryable=False,
            hint="Run without --no-interactive (and in a TTY) to log in.",
        )

    # Strip control flags; what's left maps to the core function kwargs.
    raw = vars(ns).copy()
    for f in (
        *_COMMON_FLAGS,
        "_meta",
        "_noun",
        "_verb",
        "noun",
        "verb",
        # top-level parser flags share the namespace with subparsers
        "list_commands",
        "top_json",
        # injected tab positional for browser_or_tab tools (passed positionally)
        "browser_or_tab",
    ):
        raw.pop(f, None)
    port = raw.pop("port", None) if requires_tab else None
    kwargs = {k.replace("-", "_"): v for k, v in raw.items()}

    try:
        if requires_tab:
            data = _run_with_tab(func, port, kwargs, is_async)
        else:
            data = func(**kwargs) if not is_async else asyncio.run(func(**kwargs))
    except SystemExit:  # argparse-style exits propagate
        raise
    except Exception as e:  # noqa: BLE001 - top-level CLI boundary
        code, retryable, hint = _classify(str(e))
        return _emit_error(
            str(e), as_json=as_json, code=code, retryable=retryable, hint=hint
        )

    # Normalize the return value the same way wrap_core does, so output
    # shape matches the per-tool modules exactly (SSOT).
    data = _normalize_result(data, result_key)

    # If the normalized result is a pure error dict, route it to stderr with a
    # classified exit code (no data on stdout).
    if isinstance(data, dict) and "error" in data and set(data) <= {"error", "hint"}:
        msg = str(data["error"])
        code, retryable, hint = _classify(msg)
        hint = data.get("hint") or hint
        return _emit_error(
            msg, as_json=as_json, code=code, retryable=retryable, hint=hint
        )

    # Tools that report a soft failure via `{result_key: False}` (e.g.
    # click/find that found no target) return a useful structured payload
    # AND should signal failure via exit code so a shell `$?` branches
    # correctly. Emit the payload to stdout (rule 8: explicit no-op output)
    # but exit non-zero (rule 4).
    exit_code = EXIT_OK
    if isinstance(data, dict) and data.get(result_key) is False:
        exit_code = EXIT_NOT_FOUND

    _emit_data(data, as_json=as_json, quiet=quiet, full=full)
    return exit_code


def _run_with_tab(
    func: Callable, port: int | None, kwargs: dict, is_async: bool
) -> Any:
    """Connect to a browser, grab the active tab, call the tool."""
    from ai_dev_browser.core import connect_browser, get_active_tab

    async def run() -> Any:
        browser = await connect_browser(port=port)
        tab = await get_active_tab(browser)
        if is_async:
            return await func(tab, **kwargs)
        return func(tab, **kwargs)

    return asyncio.run(run())


def _normalize_result(result: Any, result_key: str) -> Any:
    """Mirror wrap_core's return normalization (bool/dict/list/scalar)."""
    if isinstance(result, bool):
        return {result_key: True} if result else {"error": "Operation failed"}
    if isinstance(result, dict):
        return {k: v for k, v in result.items() if _json_safe(v)}
    if isinstance(result, list):
        return result
    return {result_key: result}


def _json_safe(v: Any) -> bool:
    try:
        json.dumps(v)
        return True
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Top-level argument parsing (noun → verb → leaf).
# ---------------------------------------------------------------------------
def _make_top_parser(
    tree: dict[str, dict[str, dict[str, Any]]],
) -> argparse.ArgumentParser:
    """Build the `browser` → `<noun>` → `<verb>` parser hierarchy."""
    parser = argparse.ArgumentParser(
        prog="browser",
        description=(
            "Agent-friendly browser automation CLI (noun-then-verb).\n"
            "Run `browser <noun> --help` for verbs, "
            "`browser <noun> <verb> --help` for flags."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--list",
        action="store_true",
        default=False,
        dest="list_commands",
        help="List the full noun-verb command tree and exit (use --json for JSON)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        dest="top_json",
        help="JSON output for --list",
    )
    nouns = parser.add_subparsers(dest="noun", metavar="<noun>")
    for noun in sorted(tree):
        verbs_meta = tree[noun]
        verb_names = ", ".join(sorted(verbs_meta))
        noun_parser = nouns.add_parser(
            noun,
            help=verb_names,
            description=f"{noun} commands: {verb_names}",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        verbs = noun_parser.add_subparsers(dest="verb", metavar="<verb>")
        for verb in sorted(verbs_meta):
            meta = verbs_meta[verb]
            sub = verbs.add_parser(
                verb,
                prog=f"browser {noun} {verb}",
                help=(meta["func"].__doc__ or "").strip().split("\n")[0][:70],
                formatter_class=argparse.RawDescriptionHelpFormatter,
                description=meta["func"].__doc__,
            )
            _populate_leaf(sub, meta)
            sub.set_defaults(_meta=meta, _noun=noun, _verb=verb)
    return parser


def _print_command_list(
    tree: dict[str, dict[str, dict[str, Any]]], *, as_json: bool
) -> None:
    """Print the full noun-verb tree (honors the downstream `browser --list`)."""
    if as_json or not sys.stdout.isatty():
        commands = [
            {
                "command": f"{noun} {verb}",
                "noun": noun,
                "verb": verb,
                "core": meta["name"],
                "summary": (meta["func"].__doc__ or "").strip().split("\n")[0][:80],
            }
            for noun in sorted(tree)
            for verb, meta in sorted(tree[noun].items())
        ]
        print(
            json.dumps(
                {"commands": commands, "count": len(commands)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    for noun in sorted(tree):
        verbs = ", ".join(sorted(tree[noun]))
        print(f"{noun}: {verbs}")


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``browser`` console script."""
    # AI_DEV_BROWSER_REDIRECT lets an embedding app intercept direct use,
    # mirroring the per-tool modules' behavior.
    redirect = os.environ.get("AI_DEV_BROWSER_REDIRECT")
    if redirect:
        print(redirect, file=sys.stderr)
        return 1

    argv = list(sys.argv[1:] if argv is None else argv)
    tree = _build_tree()
    parser = _make_top_parser(tree)

    ns = parser.parse_args(argv)

    if getattr(ns, "list_commands", False):
        _print_command_list(tree, as_json=getattr(ns, "top_json", False))
        return EXIT_OK

    if not getattr(ns, "noun", None):
        parser.print_help()
        return EXIT_OK
    if not getattr(ns, "verb", None):
        # `browser <noun>` with no verb: show that noun's verbs.
        noun = ns.noun
        verbs = ", ".join(sorted(tree[noun]))
        print(f"usage: browser {noun} <verb> [flags]", file=sys.stderr)
        print(f"verbs: {verbs}", file=sys.stderr)
        return EXIT_VALIDATION

    meta = getattr(ns, "_meta", None)
    if meta is None:  # pragma: no cover - defensive
        parser.print_help()
        return EXIT_VALIDATION
    return _run_tool(meta, ns)


if __name__ == "__main__":
    sys.exit(main())
