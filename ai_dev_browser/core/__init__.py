"""Core browser operations - shared by tools/ and Python package.

This module provides async functions for common browser operations.
Both CLI tools and Python code can use these functions.

Usage:
    from ai_dev_browser.core import page_goto, click_by_text, page_discover

    # In async context
    await page_goto(tab, "https://example.com")
    await click_by_text(tab, text="Sign in")
    result = await page_discover(tab, interactable_only=True)
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
from .cloudflare import cloudflare_verify
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
    get_workspace_profile_dir,
    get_workspace_slug,
)

# Connection
from .connection import connect_browser, get_active_tab, graceful_close_browser

# Cookies
from .cookies import cookies_list, cookies_load, cookies_save

# Dialog (only tool-facing function)
from .dialog import dialog_respond

# Download
from .download import download

# Login (human-in-the-loop)
from .login import login_interactive

# Elements (only tool-facing functions)
from .elements import (
    click_by_html_id,
    click_by_text,
    click_by_xpath,
    find_by_html_id,
    find_by_xpath,
    page_scroll,
    page_wait_element,
    type_by_text,
)

# Mouse
from .mouse import mouse_click, mouse_drag, mouse_move

# Navigation (only tool-facing functions)
from .navigation import (
    page_goto,
    page_reload,
    page_wait_ready,
    page_wait_url,
)

# Page info
from .page import page_html, page_info, js_evaluate, page_screenshot

# Port management
from .port import (
    find_debug_chromes,
    find_workspace_chromes,
    get_available_port,
    is_port_in_use,
)

# Process management
from .process import get_pid_on_port

# Text matching (only the dataclass is public)
from .text_match import MatchResult

# Snapshot (AI-friendly accessibility tree) - only tool-facing function
from .snapshot import page_discover

# Storage
from .storage import storage_get, storage_set

# Tabs
from .tabs import tab_close, tab_list, tab_new, tab_switch

# Window
from .window import page_emulate_focus, window_set


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
    "get_workspace_slug",
    "get_workspace_profile_dir",
    # Chrome
    "find_chrome",
    "launch_chrome",
    # Cloudflare
    "cloudflare_verify",
    # CDP
    "cdp_send",
    # Port
    "is_port_in_use",
    "find_debug_chromes",
    "find_workspace_chromes",
    "get_available_port",
    # Process
    "get_pid_on_port",
    # Connection
    "connect_browser",
    "get_active_tab",
    "graceful_close_browser",
    # Navigation
    "page_goto",
    "page_reload",
    "page_wait_ready",
    "page_wait_url",
    # Elements
    "click_by_text",
    "type_by_text",
    "page_scroll",
    "page_wait_element",
    "find_by_html_id",
    "click_by_html_id",
    "find_by_xpath",
    "click_by_xpath",
    # Text matching
    "MatchResult",
    # Snapshot
    "page_discover",
    # Tabs
    "tab_new",
    "tab_list",
    "tab_switch",
    "tab_close",
    # Page
    "page_info",
    "page_html",
    "js_evaluate",
    "page_screenshot",
    # Mouse
    "mouse_move",
    "mouse_click",
    "mouse_drag",
    # Window
    "window_set",
    "page_emulate_focus",
    # Storage
    "storage_get",
    "storage_set",
    # Download
    "download",
    # Dialog
    "dialog_respond",
    # Login
    "login_interactive",
    # Cookies
    "cookies_load",
    "cookies_save",
    "cookies_list",
]
