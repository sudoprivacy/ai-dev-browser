#!/usr/bin/env python3
"""Generate tool wrapper files from core functions.

Auto-discovers public functions from core.__all__ and generates CLI tools.
Functions are excluded if they're in INTERNAL (infrastructure, not user-facing).

Usage:
    python -m ai_dev_browser.tools._generate
"""

import inspect
from pathlib import Path

# Functions in core.__all__ that should NOT become CLI tools.
# These are infrastructure functions used internally by the CLI wrapper.
INTERNAL = {
    "find_chrome",
    "launch_chrome",
    "is_port_in_use",
    "find_debug_chromes",
    "find_workspace_chromes",
    "get_available_port",
    "get_pid_on_port",
    "get_workspace_slug",
    "get_workspace_profile_dir",
    "graceful_close_browser",
    "connect_browser",
    "get_active_tab",
}

# Per-tool metadata overrides. Key = function name, value = dict of overrides.
# Defaults: requires_tab=True (auto-detected from first param), result_key="success"
TOOL_META = {
    "browser_start": {"result_key": "port"},
    "browser_stop": {"result_key": "stopped"},
    "browser_list": {"result_key": "count"},
    "click_by_ref": {"result_key": "clicked"},
    "click_by_text": {"result_key": "clicked"},
    "click_by_html_id": {"result_key": "clicked"},
    "click_by_xpath": {"result_key": "clicked"},
    "find_by_html_id": {"result_key": "found"},
    "find_by_xpath": {"result_key": "found"},
    "type_by_ref": {"result_key": "typed"},
    "type_by_text": {"result_key": "typed"},
    "focus_by_ref": {"result_key": "focused"},
    "hover_by_ref": {"result_key": "hovered"},
    "highlight_by_ref": {"result_key": "highlighted"},
    "html_by_ref": {"result_key": "html"},
    "screenshot_by_ref": {"result_key": "path"},
    "select_by_ref": {"result_key": "selected"},
    "upload_by_ref": {"result_key": "uploaded"},
    "drag_by_ref": {"result_key": "dragged"},
    "page_discover": {"result_key": "elements"},
    "find": {"result_key": "elements"},
    "page_wait_element": {"result_key": "found"},
    "js_evaluate": {"result_key": "result"},
    "page_goto": {"result_key": "success"},
    "page_info": {"result_key": "url"},
    "page_html": {"result_key": "html"},
    "page_reload": {"result_key": "success"},
    "page_screenshot": {"result_key": "path"},
    "screenshot": {"result_key": "path"},
    "page_scroll": {"result_key": "scrolled"},
    "scroll": {"result_key": "scrolled"},
    "page_wait_ready": {"result_key": "ready"},
    "page_wait_url": {"result_key": "matched"},
    "dialog_respond": {"result_key": "handled"},
    "mouse_click": {"result_key": "clicked"},
    "mouse_move": {"result_key": "moved"},
    "mouse_drag": {"result_key": "dragged"},
    "tab_new": {"result_key": "tab_id"},
    "tab_list": {"result_key": "tabs"},
    "tab_switch": {"result_key": "switched"},
    "tab_close": {"result_key": "closed"},
    "cookies_load": {"result_key": "loaded"},
    "cookies_save": {"result_key": "saved"},
    "cookies_list": {"result_key": "cookies"},
    "storage_get": {"result_key": "value"},
    "storage_set": {"result_key": "set"},
    "window_focus": {"result_key": "focused"},
    "window_focus_emulation": {"result_key": "set"},
    "window_resize": {"result_key": "resized"},
    "window_state": {"result_key": "state"},
    "download_file": {"result_key": "path"},
    "download_path": {"result_key": "path"},
    "cdp_send": {"result_key": "result"},
    "cloudflare_verify": {"result_key": "verified"},
    "login_interactive": {"result_key": "success"},
    "reload": {"result_key": "success"},
}

TEMPLATE = '''"""AUTO-GENERATED from ai_dev_browser.core — {func_name}
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import {func_name} as _core_func

from .._cli import as_cli, wrap_core


{func_name} = as_cli({no_tab})(wrap_core(_core_func, "{result_key}"))

if __name__ == "__main__":
    {func_name}.cli_main()
'''

TEMPLATE_SYNC = '''"""AUTO-GENERATED from ai_dev_browser.core — {func_name}
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import {func_name} as _core_func

from .._cli import as_cli, wrap_core_sync


{func_name} = as_cli({no_tab})(wrap_core_sync(_core_func, "{result_key}"))

if __name__ == "__main__":
    {func_name}.cli_main()
'''


def _discover_tools():
    """Auto-discover tool functions from core.__all__."""
    from ai_dev_browser.core import __all__ as core_all
    import ai_dev_browser.core as core_module

    tools = []
    for name in sorted(core_all):
        if name in INTERNAL:
            continue
        obj = getattr(core_module, name, None)
        if obj is None:
            continue
        if not (inspect.isfunction(obj) or inspect.iscoroutinefunction(obj)):
            continue

        # Detect requires_tab from first parameter name
        sig = inspect.signature(obj)
        params = list(sig.parameters.keys())
        first_param = params[0] if params else ""
        requires_tab = first_param in ("tab", "browser_or_tab")

        # Get metadata
        meta = TOOL_META.get(name, {})
        result_key = meta.get("result_key", "success")
        is_async = inspect.iscoroutinefunction(obj)

        tools.append(
            {
                "name": name,
                "result_key": result_key,
                "requires_tab": requires_tab,
                "is_async": is_async,
            }
        )

    return tools


def main():
    """Generate all tool files."""
    tools_dir = Path(__file__).parent
    tools = _discover_tools()

    generated = []
    skipped = []

    for tool in tools:
        name = tool["name"]
        file_path = tools_dir / f"{name}.py"

        no_tab = "requires_tab=False" if not tool["requires_tab"] else ""
        template = TEMPLATE if tool["is_async"] else TEMPLATE_SYNC

        content = template.format(
            func_name=name,
            result_key=tool["result_key"],
            no_tab=no_tab,
        )

        if file_path.exists():
            existing = file_path.read_text()
            if existing == content:
                skipped.append(name)
                continue

        file_path.write_text(content)
        generated.append(name)
        print(f"Generated: {name}.py")

    # Report orphan tool files (exist on disk but not discovered)
    expected = {t["name"] for t in tools}
    for f in tools_dir.glob("*.py"):
        if f.name.startswith("_") or f.name == "__init__.py":
            continue
        stem = f.stem
        if stem not in expected:
            print(f"ORPHAN (delete?): {f.name}")

    print(f"\nGenerated: {len(generated)} files")
    print(f"Skipped (unchanged): {len(skipped)} files")
    print(f"Total tools: {len(tools)}")


if __name__ == "__main__":
    main()
