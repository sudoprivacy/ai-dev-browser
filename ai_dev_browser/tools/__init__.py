"""Browser automation tools.

Each tool can be used as:
- CLI: python -m ai_dev_browser.tools.<name> --arg value
- Python: from ai_dev_browser.tools import <name>; await <name>(tab, ...)

Discovery:
    ls ai_dev_browser/tools/  # See all available tools
"""

# Browser management (no tab required)
from .browser_list import browser_list
from .browser_start import browser_start
from .browser_stop import browser_stop

# CDP & Cloudflare
from .cdp_send import cdp_send
from .cf_verify import cf_verify

# Click actions (primary for AI)
from .click_by_ref import click_by_ref
from .click_by_text import click_by_text

# Cookies
from .cookies_list import cookies_list
from .cookies_load import cookies_load
from .cookies_save import cookies_save

# Download
from .download_file import download_file
from .download_path import download_path

# Element wait
from .element_wait import element_wait

# Find (main discovery tool for AI)
from .page_find import page_find

# Focus
from .focus_by_ref import focus_by_ref

# Interactive login (human-in-the-loop, no tab required)
from .login_interactive import login_interactive

# JavaScript execution
from .js_exec import js_exec

# Mouse actions
from .mouse_click import mouse_click
from .mouse_drag import mouse_drag
from .mouse_move import mouse_move

# Page actions
from .page_goto import page_goto
from .page_handle_dialog import page_handle_dialog
from .page_html import page_html
from .page_info import page_info
from .page_reload import page_reload
from .page_screenshot import page_screenshot
from .page_wait import page_wait
from .page_wait_url import page_wait_url
from .page_scroll import page_scroll

# Storage
from .storage_get import storage_get
from .storage_set import storage_set

# Tab actions
from .tab_close import tab_close
from .tab_list import tab_list
from .tab_new import tab_new
from .tab_switch import tab_switch

# Type actions (primary for AI)
from .type_by_ref import type_by_ref
from .type_by_text import type_by_text

# Window
from .window_focus import window_focus
from .window_focus_emulation import window_focus_emulation
from .window_resize import window_resize
from .window_state import window_state


__all__ = [
    # Browser
    "browser_list",
    "browser_start",
    "browser_stop",
    # Click (primary for AI)
    "click_by_ref",
    "click_by_text",
    # Element
    "element_wait",
    # Find (main discovery tool for AI)
    "page_find",
    # Focus
    "focus_by_ref",
    # JavaScript
    "js_exec",
    # Page
    "page_goto",
    "page_handle_dialog",
    "page_html",
    "page_info",
    "page_reload",
    "page_wait",
    "page_wait_url",
    "page_screenshot",
    "page_scroll",
    # Login (human-in-the-loop)
    "login_interactive",
    # Mouse
    "mouse_click",
    "mouse_drag",
    "mouse_move",
    # Tabs
    "tab_close",
    "tab_list",
    "tab_new",
    "tab_switch",
    # Type (primary for AI)
    "type_by_ref",
    "type_by_text",
    # Cookies
    "cookies_list",
    "cookies_load",
    "cookies_save",
    # Storage
    "storage_get",
    "storage_set",
    # Window
    "window_focus",
    "window_focus_emulation",
    "window_resize",
    "window_state",
    # Download
    "download_file",
    "download_path",
    # CDP & CF
    "cdp_send",
    "cf_verify",
]
