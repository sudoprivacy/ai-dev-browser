"""Unified CLI dispatcher for ai-dev-browser.

Usage:
    python -m ai_dev_browser <tool> [args]
    python -m ai_dev_browser --list
    python -m ai_dev_browser <tool> --help

Examples:
    python -m ai_dev_browser browser-start
    python -m ai_dev_browser page-find --query "button"
    python -m ai_dev_browser page-goto --url "https://example.com"
"""

import importlib
import pkgutil
import sys


def _list_tools() -> list[str]:
    """List all available tool names."""
    import ai_dev_browser.tools as tools_pkg

    return sorted(
        m.name
        for m in pkgutil.iter_modules(tools_pkg.__path__)
        if not m.name.startswith("_")
    )


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("ai-dev-browser: AI-native browser automation toolkit")
        print()
        print("Usage: python -m ai_dev_browser <tool> [args]")
        print()
        print("Options:")
        print("  --list     List all available tools")
        print("  --help     Show this help message")
        print()
        print("Examples:")
        print("  python -m ai_dev_browser browser-start")
        print("  python -m ai_dev_browser page-find --query 'button'")
        print("  python -m ai_dev_browser page-goto --url 'https://example.com'")
        print()
        print("Run '<tool> --help' for tool-specific help.")
        return

    if sys.argv[1] == "--list":
        for name in _list_tools():
            print(name)
        return

    # Resolve tool name: accept both "page-find" and "page_find"
    tool_name = sys.argv[1].replace("-", "_")

    # Validate tool exists
    available = _list_tools()
    if tool_name not in available:
        print(f"Error: unknown tool '{sys.argv[1]}'", file=sys.stderr)
        print(f"Run 'python -m ai_dev_browser --list' to see available tools.", file=sys.stderr)
        sys.exit(1)

    # Rewrite sys.argv so the tool sees its own args
    sys.argv = [f"ai_dev_browser.tools.{tool_name}"] + sys.argv[2:]

    # Import and run the tool
    mod = importlib.import_module(f"ai_dev_browser.tools.{tool_name}")

    # Find the CLI-decorated function (same name as module)
    func = getattr(mod, tool_name, None)
    if func and hasattr(func, "cli_main"):
        func.cli_main()
    else:
        print(f"Error: tool '{tool_name}' has no cli_main entry point", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
