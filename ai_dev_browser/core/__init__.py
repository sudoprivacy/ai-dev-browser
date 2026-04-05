"""Core browser operations - shared by tools/ and Python package.

This module provides async functions for common browser operations.
Both CLI tools and Python code can use these functions.

Usage:
    from ai_dev_browser.core import page_goto, click_by_text, page_find

    # In async context
    await page_goto(tab, "https://example.com")
    await click_by_text(tab, text="Sign in")
    result = await page_find(tab, interactable_only=True)
"""

# Accessibility tree interactions
# CDP
# Config (shared constants)
from .ax import (
    click_by_ref,
    drag_by_ref,
    focus_by_ref,
    highlight_by_ref,
    hover_by_ref,
    html_by_ref,
    screenshot_by_ref,
    select_by_ref,
    type_by_ref,
    upload_by_ref,
)

# Browser lifecycle
from .browser import browser_list, browser_start, browser_stop
from .cdp import cdp_send

# Chrome detection and launching
from .chrome import find_chrome, launch_chrome

# Cloudflare
from .cloudflare import cf_verify
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
from .cookies import cookies_list, cookies_load, cookies_save

# Dialog (only tool-facing function)
from .dialog import page_handle_dialog

# Download
from .download import download_file, download_path

# Login (human-in-the-loop)
from .login import login_interactive

# Elements (only tool-facing functions)
from .elements import (
    click_by_text,
    page_scroll,
    type_by_text,
    element_wait,
)

# Mouse
from .mouse import mouse_click, mouse_drag, mouse_move

# Navigation (only tool-facing functions)
from .navigation import (
    page_goto,
    page_reload,
    page_wait,
    page_wait_url,
)

# Page info
from .page import page_html, page_info, js_exec, page_screenshot

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
from .snapshot import page_find

# Storage
from .storage import storage_get, storage_set

# Tabs
from .tabs import tab_close, tab_list, tab_new, tab_switch

# Window
from .window import window_focus, window_resize, window_focus_emulation, window_state


__all__ = [
    # Accessibility tree interactions (by ref)
    "click_by_ref",
    "drag_by_ref",
    "focus_by_ref",
    "highlight_by_ref",
    "hover_by_ref",
    "html_by_ref",
    "screenshot_by_ref",
    "select_by_ref",
    "type_by_ref",
    "upload_by_ref",
    # Browser lifecycle
    "browser_start",
    "browser_stop",
    "browser_list",
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
    "cf_verify",
    # CDP
    "cdp_send",
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
    "page_goto",
    "page_reload",
    "page_wait",
    "page_wait_url",
    # Elements
    "click_by_text",
    "type_by_text",
    "page_scroll",
    "element_wait",
    # Text matching
    "MatchResult",
    # Snapshot
    "page_find",
    # Tabs
    "tab_new",
    "tab_list",
    "tab_switch",
    "tab_close",
    # Page
    "page_info",
    "page_html",
    "js_exec",
    "page_screenshot",
    # Mouse
    "mouse_move",
    "mouse_click",
    "mouse_drag",
    # Window
    "window_resize",
    "window_state",
    "window_focus_emulation",
    "window_focus",
    # Storage
    "storage_get",
    "storage_set",
    # Download
    "download_path",
    "download_file",
    # Dialog
    "page_handle_dialog",
    # Login
    "login_interactive",
    # Cookies
    "cookies_load",
    "cookies_save",
    "cookies_list",
]
