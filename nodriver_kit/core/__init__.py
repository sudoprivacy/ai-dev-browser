"""Core browser operations - shared by tools/ and Python package.

This module provides async functions for common browser operations.
Both CLI tools and Python code can use these functions.

Usage:
    from nodriver_kit.core import goto, click, get_snapshot

    # In async context
    await goto(tab, "https://example.com")
    await click(tab, text="Sign in")
    snapshot = await get_snapshot(tab, interactable_only=True)
"""

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

__all__ = [
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
]
