"""Core browser operations - shared by tools/ and Python package.

This module provides async functions for common browser operations.
Both CLI tools and Python code can use these functions.

Usage:
    from ai_dev_browser.core import goto, click_by_text, find

    # In async context
    await goto(tab, "https://example.com")
    await click_by_text(tab, text="Sign in")
    result = await find(tab, interactable_only=True)
"""

# Accessibility tree interactions
# CDP
# Config (shared constants)
from .ax import (
    click_by_ref,
    focus_by_ref,
    type_by_ref,
)

# Browser lifecycle
from .browser import list_browsers, start_browser, stop_browser
from .cdp import send_cdp_command

# Chrome detection and launching
from .chrome import find_chrome, launch_chrome

# Cloudflare
from .cloudflare import verify_cloudflare
from .config import (
    DEFAULT_BASE_DIR,
    DEFAULT_COOKIES_DIR,
    DEFAULT_COOKIES_FILE,
    DEFAULT_DEBUG_HOST,
    DEFAULT_DEBUG_PORT,
    DEFAULT_PORT_RANGE,
    DEFAULT_PROFILE_DIR,
    DEFAULT_PROFILE_PREFIX,
    DEFAULT_REUSE_STRATEGY,
    ReuseStrategy,
)

# Connection
from .connection import connect_browser, get_active_tab

# Cookies
from .cookies import list_cookies, load_cookies, save_cookies

# Dialog (only tool-facing function)
from .dialog import handle_dialog_action

# Download
from .download import download_file, set_download_path

# Elements (only tool-facing functions)
from .elements import (
    click_by_text,
    scroll,
    type_by_text,
    wait_for_element_with_info,
)

# Mouse
from .mouse import mouse_click, mouse_drag, mouse_move

# Navigation (only tool-facing functions)
from .navigation import (
    goto,
    reload,
    wait_for_load,
    wait_for_url,
)

# Page info
from .page import get_page_html, get_page_info, js_exec, screenshot

# Port management
from .port import (
    find_debug_chromes,
    get_available_port,
    is_chrome_in_use,
    is_port_in_use,
)

# Process management
from .process import get_pid_on_port, get_process_cmdline

# Text matching (only the dataclass is public)
from .text_match import MatchResult

# Snapshot (AI-friendly accessibility tree) - only tool-facing function
from .snapshot import find

# Storage
from .storage import get_local_storage, set_local_storage

# Tabs
from .tabs import close_tab, list_tabs, new_tab, switch_tab

# Window
from .window import focus_window, resize_window, set_focus_emulation, set_window_state


__all__ = [
    # Accessibility tree interactions
    "click_by_ref",
    "focus_by_ref",
    "type_by_ref",
    # Browser lifecycle
    "start_browser",
    "stop_browser",
    "list_browsers",
    # Config
    "DEFAULT_BASE_DIR",
    "DEFAULT_PROFILE_DIR",
    "DEFAULT_COOKIES_FILE",
    "DEFAULT_COOKIES_DIR",
    "DEFAULT_PROFILE_PREFIX",
    "DEFAULT_DEBUG_HOST",
    "DEFAULT_DEBUG_PORT",
    "DEFAULT_PORT_RANGE",
    "DEFAULT_REUSE_STRATEGY",
    "ReuseStrategy",
    # Chrome
    "find_chrome",
    "launch_chrome",
    # Cloudflare
    "verify_cloudflare",
    # CDP
    "send_cdp_command",
    # Port
    "is_port_in_use",
    "is_chrome_in_use",
    "find_debug_chromes",
    "get_available_port",
    # Process
    "get_pid_on_port",
    "get_process_cmdline",
    # Connection
    "connect_browser",
    "get_active_tab",
    # Navigation
    "goto",
    "reload",
    "wait_for_load",
    "wait_for_url",
    # Elements
    "click_by_text",
    "type_by_text",
    "scroll",
    "wait_for_element_with_info",
    # Text matching
    "MatchResult",
    # Snapshot
    "find",
    # Tabs
    "new_tab",
    "list_tabs",
    "switch_tab",
    "close_tab",
    # Page
    "get_page_info",
    "get_page_html",
    "js_exec",
    "screenshot",
    # Mouse
    "mouse_move",
    "mouse_click",
    "mouse_drag",
    # Window
    "resize_window",
    "set_window_state",
    "set_focus_emulation",
    "focus_window",
    # Storage
    "get_local_storage",
    "set_local_storage",
    # Download
    "set_download_path",
    "download_file",
    # Dialog
    "handle_dialog_action",
    # Cookies
    "load_cookies",
    "save_cookies",
    "list_cookies",
]
