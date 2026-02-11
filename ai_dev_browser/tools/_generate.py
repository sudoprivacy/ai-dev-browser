#!/usr/bin/env python3
"""Generate tool wrapper files from core functions.

This is the SSOT (Single Source of Truth) generator. Core functions are the
source of truth, and tool files are auto-generated from them.

Usage:
    python -m ai_dev_browser.tools._generate

After modifying core functions, run this script to regenerate tool files.
"""

from pathlib import Path

# =============================================================================
# TOOL REGISTRY - Add new tools here
# =============================================================================
# Format: (module_path, function_name, result_key)
# - module_path: relative to ai_dev_browser.core
# - function_name: the core function name (same as tool file name)
# - result_key: key for successful result in JSON output

TOOLS = [
    # Click actions
    ("elements", "click_by_text", "clicked"),
    ("ax", "click_by_ref", "clicked"),
    # Type actions
    ("elements", "type_by_text", "typed"),
    ("ax", "type_by_ref", "typed"),
    # Focus actions
    ("ax", "focus_by_ref", "focused"),
    # Find
    ("snapshot", "find", "elements"),
    # Element wait
    ("elements", "wait_for_element_with_info", "found", "element_wait"),
    # JavaScript
    ("page", "js_exec", "result"),
    # Page actions
    ("navigation", "goto", "success", "page_goto"),
    ("page", "get_page_info", "url", "page_info"),
    ("page", "get_page_html", "html", "page_html"),
    ("navigation", "reload", "success", "page_reload"),
    ("page", "screenshot", "path", "page_screenshot"),
    ("navigation", "wait_for_load", "ready", "page_wait"),
    ("navigation", "wait_for_url", "matched", "page_wait_url"),
    ("dialog", "handle_dialog_action", "handled", "page_handle_dialog"),
    ("elements", "scroll", "scrolled"),
    # Mouse actions
    ("mouse", "mouse_click", "clicked"),
    ("mouse", "mouse_move", "moved"),
    ("mouse", "mouse_drag", "dragged"),
    # Tab actions
    ("tabs", "new_tab", "tab_id", "tab_new"),
    ("tabs", "list_tabs", "tabs", "tab_list"),
    ("tabs", "switch_tab", "switched", "tab_switch"),
    ("tabs", "close_tab", "closed", "tab_close"),
    # Browser management (no tab required)
    ("browser", "start_browser", "port", "browser_start"),
    ("browser", "stop_browser", "stopped", "browser_stop"),
    ("browser", "list_browsers", "count", "browser_list"),
    # Cookies
    ("cookies", "load_cookies", "loaded", "cookies_load"),
    ("cookies", "save_cookies", "saved", "cookies_save"),
    ("cookies", "list_cookies", "cookies", "cookies_list"),
    # Storage
    ("storage", "get_local_storage", "value", "storage_get"),
    ("storage", "set_local_storage", "set", "storage_set"),
    # Window
    ("window", "focus_window", "focused", "window_focus"),
    ("window", "set_focus_emulation", "set", "window_focus_emulation"),
    ("window", "resize_window", "resized", "window_resize"),
    ("window", "set_window_state", "state", "window_state"),
    # Download
    ("download", "download_file", "path", "download_file"),
    ("download", "set_download_path", "path", "download_path"),
    # CDP & Cloudflare
    ("cdp", "send_cdp_command", "result", "cdp_send"),
    ("cloudflare", "verify_cloudflare", "verified", "cf_verify"),
]

# Tools that don't require a browser tab
NO_TAB_TOOLS = {
    "browser_start",
    "browser_stop",
    "browser_list",
}

TEMPLATE = '''"""AUTO-GENERATED from ai_dev_browser.core.{module}.{func_name}
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.{module} import {func_name} as _core_func

from .._cli import as_cli, wrap_core


{tool_name} = as_cli({no_tab})(wrap_core(_core_func, "{result_key}"))

if __name__ == "__main__":
    {tool_name}.cli_main()
'''

TEMPLATE_SYNC = '''"""AUTO-GENERATED from ai_dev_browser.core.{module}.{func_name}
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.{module} import {func_name} as _core_func

from .._cli import as_cli, wrap_core_sync


{tool_name} = as_cli({no_tab})(wrap_core_sync(_core_func, "{result_key}"))

if __name__ == "__main__":
    {tool_name}.cli_main()
'''


def generate_tool_file(
    module: str, func_name: str, result_key: str, tool_name: str = None
) -> str:
    """Generate tool file content."""
    if tool_name is None:
        tool_name = func_name

    no_tab = "requires_tab=False" if tool_name in NO_TAB_TOOLS else ""

    # Use sync template for browser management functions
    if tool_name in NO_TAB_TOOLS:
        template = TEMPLATE_SYNC
    else:
        template = TEMPLATE

    return template.format(
        module=module,
        func_name=func_name,
        tool_name=tool_name,
        result_key=result_key,
        no_tab=no_tab,
    )


def main():
    """Generate all tool files."""
    tools_dir = Path(__file__).parent

    generated = []
    skipped = []

    for entry in TOOLS:
        if len(entry) == 3:
            module, func_name, result_key = entry
            tool_name = func_name
        else:
            module, func_name, result_key, tool_name = entry

        file_path = tools_dir / f"{tool_name}.py"
        content = generate_tool_file(module, func_name, result_key, tool_name)

        # Check if file exists and has same content
        if file_path.exists():
            existing = file_path.read_text()
            if existing == content:
                skipped.append(tool_name)
                continue

        file_path.write_text(content)
        generated.append(tool_name)
        print(f"Generated: {tool_name}.py")

    print(f"\nGenerated: {len(generated)} files")
    print(f"Skipped (unchanged): {len(skipped)} files")

    # List all tool files
    print(f"\nAll tools ({len(TOOLS)}):")
    for entry in sorted(TOOLS, key=lambda x: x[-1] if len(x) == 4 else x[1]):
        tool_name = entry[-1] if len(entry) == 4 else entry[1]
        print(f"  - {tool_name}")


if __name__ == "__main__":
    main()
