"""Core browser operations - shared by tools/ and Python package.

This module provides async functions for common browser operations.
Both CLI tools and Python code can use these functions.

Usage:
    from ai_dev_browser.core import goto, click, get_snapshot

    # In async context
    await goto(tab, "https://example.com")
    await click(tab, text="Sign in")
    snapshot = await get_snapshot(tab, interactable_only=True)
"""

# Accessibility tree interactions
# CDP
# Config (shared constants)
# Human-like behavior
from . import human
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

# Dialog
from .dialog import (
    handle_dialog,
    handle_dialog_action,
    setup_auto_dialog_handler,
    wait_for_dialog,
)

# Download
from .download import download_file, set_download_path

# Elements
from .elements import (
    click,
    click_by_text,
    find_by_xpath,
    find_element,
    find_element_info,
    find_elements,
    focus_element,
    fuzzy_click,
    fuzzy_find,
    fuzzy_find_all,
    get_element_text,
    scroll,
    type_by_text,
    type_text,
    wait_for_element,
    wait_for_element_with_info,
)

# Mouse
from .mouse import mouse_click, mouse_drag, mouse_move

# Navigation
from .navigation import (
    back,
    forward,
    goto,
    reload,
    wait_for_load,
    wait_for_page,
    wait_for_url,
    wait_for_url_match,
)

# Overlays
from .overlays import dismiss_overlays

# Page info
from .page import get_page_html, get_page_info, js_exec, screenshot

# Port management
from .port import (
    cleanup_temp_profile,
    find_ai_dev_browser_chromes,
    find_debug_chromes,
    find_our_chromes,
    get_available_port,
    is_ai_dev_browser_chrome_on_port,
    is_chrome_in_use,
    is_our_chrome_on_port,
    is_port_in_use,
)

# Process management
from .process import get_pid_on_port, get_process_cmdline, kill_process_tree

# Session management
from .session import extract_session_id, get_session_id, is_our_session

# Text matching
from .text_match import match_score, best_match, all_matches, MatchResult

# Snapshot (AI-friendly accessibility tree)
from .snapshot import find, get_accessibility_tree, get_snapshot

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
    "is_our_chrome_on_port",
    "is_ai_dev_browser_chrome_on_port",
    "is_chrome_in_use",
    "find_our_chromes",
    "find_ai_dev_browser_chromes",
    "find_debug_chromes",
    "get_available_port",
    "cleanup_temp_profile",
    # Session
    "get_session_id",
    "is_our_session",
    "extract_session_id",
    # Process
    "get_pid_on_port",
    "get_process_cmdline",
    "kill_process_tree",
    # Connection
    "connect_browser",
    "get_active_tab",
    # Navigation
    "goto",
    "back",
    "forward",
    "reload",
    "wait_for_load",
    "wait_for_page",
    "wait_for_url",
    "wait_for_url_match",
    # Elements
    "find_element",
    "find_element_info",
    "find_elements",
    "find_by_xpath",
    "click",
    "click_by_text",
    "type_by_text",
    "type_text",
    "scroll",
    "wait_for_element",
    "wait_for_element_with_info",
    "focus_element",
    "get_element_text",
    "fuzzy_find",
    "fuzzy_find_all",
    "fuzzy_click",
    # Text matching
    "match_score",
    "best_match",
    "all_matches",
    "MatchResult",
    # Snapshot
    "find",
    "get_snapshot",
    "get_accessibility_tree",
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
    # Overlays
    "dismiss_overlays",
    # Dialog
    "handle_dialog",
    "handle_dialog_action",
    "wait_for_dialog",
    "setup_auto_dialog_handler",
    # Human-like behavior
    "human",
    # Cookies
    "load_cookies",
    "save_cookies",
    "list_cookies",
]
