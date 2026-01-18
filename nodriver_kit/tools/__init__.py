"""Browser automation tools.

Each tool can be used as:
- CLI: python -m nodriver_kit.tools.<name> --arg value
- Python: from nodriver_kit.tools import <name>; await <name>(tab, ...)

Discovery:
    ls nodriver_kit/tools/  # See all available tools
"""

# Browser management (no tab required)
from .browser_list import browser_list
from .browser_start import browser_start
from .browser_stop import browser_stop

# Page actions
from .click import click
from .element_wait import element_wait
from .evaluate import evaluate
from .find import find
from .goto import goto
from .html import html
from .page_info import page_info
from .page_wait import page_wait
from .reload import reload
from .screenshot import screenshot
from .scroll import scroll
from .snapshot import snapshot  # deprecated, use ax_tree
from .type_text import type_text
from .wait_url import wait_url
from .xpath import xpath

# Accessibility tree
from .ax_tree import ax_tree
from .ax_select import ax_select

# Session
from .login_interactive import login_interactive

# Mouse actions
from .mouse_click import mouse_click
from .mouse_drag import mouse_drag
from .mouse_move import mouse_move

# Tab actions
from .tab_close import tab_close
from .tab_list import tab_list
from .tab_new import tab_new
from .tab_switch import tab_switch

# Cookies
from .cookies_list import cookies_list
from .cookies_load import cookies_load
from .cookies_save import cookies_save

# Storage
from .storage_get import storage_get
from .storage_set import storage_set

# Window
from .window_resize import window_resize
from .window_state import window_state

# Download
from .download_file import download_file
from .download_path import download_path

# CDP & Cloudflare
from .cdp_send import cdp_send
from .cf_verify import cf_verify

__all__ = [
    # Browser
    "browser_list",
    "browser_start",
    "browser_stop",
    # Page
    "click",
    "element_wait",
    "evaluate",
    "find",
    "goto",
    "html",
    "page_info",
    "page_wait",
    "reload",
    "screenshot",
    "scroll",
    "snapshot",  # deprecated, use ax_tree
    "type_text",
    "wait_url",
    "xpath",
    # Accessibility tree
    "ax_tree",
    "ax_select",
    # Session
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
    # Cookies
    "cookies_list",
    "cookies_load",
    "cookies_save",
    # Storage
    "storage_get",
    "storage_set",
    # Window
    "window_resize",
    "window_state",
    # Download
    "download_file",
    "download_path",
    # CDP & CF
    "cdp_send",
    "cf_verify",
]
