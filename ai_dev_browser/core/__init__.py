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

# Config (shared constants)
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

# Chrome detection and launching
from .chrome import find_chrome, launch_chrome

# Port management
from .port import (
    cleanup_temp_profile,
    find_debug_chromes,
    find_ai_dev_browser_chromes,
    find_our_chromes,
    get_available_port,
    is_chrome_in_use,
    is_ai_dev_browser_chrome_on_port,
    is_our_chrome_on_port,
    is_port_in_use,
)

# Session management
from .session import get_session_id, is_our_session, extract_session_id

# Process management
from .process import get_pid_on_port, get_process_cmdline, kill_process_tree

# Connection
from .connection import connect_browser, get_active_tab

# Navigation
from .navigation import goto, back, forward, reload, wait_for_load, wait_for_url

# Elements
from .elements import (
    find_element,
    find_elements,
    find_by_xpath,
    click,
    type_text,
    scroll,
    wait_for_element,
)

# Snapshot (AI-friendly accessibility tree)
from .snapshot import get_snapshot

# Tabs
from .tabs import new_tab, list_tabs, switch_tab, close_tab

# Page info
from .page import get_page_info

# Mouse
from .mouse import mouse_move, mouse_click, mouse_drag

# Window
from .window import resize_window, set_window_state

# Storage
from .storage import get_local_storage, set_local_storage

# Download
from .download import set_download_path, download_file

# Overlays
from .overlays import dismiss_overlays

__all__ = [
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
    "wait_for_url",
    # Elements
    "find_element",
    "find_elements",
    "find_by_xpath",
    "click",
    "type_text",
    "scroll",
    "wait_for_element",
    # Snapshot
    "get_snapshot",
    # Tabs
    "new_tab",
    "list_tabs",
    "switch_tab",
    "close_tab",
    # Page
    "get_page_info",
    # Mouse
    "mouse_move",
    "mouse_click",
    "mouse_drag",
    # Window
    "resize_window",
    "set_window_state",
    # Storage
    "get_local_storage",
    "set_local_storage",
    # Download
    "set_download_path",
    "download_file",
    # Overlays
    "dismiss_overlays",
]
