"""Browser management module.

Provides cross-platform Chrome detection, launching, and port management.

Example:
    from nodriver_kit.browser import find_chrome, launch_chrome, get_available_port

    port = get_available_port()
    process = launch_chrome(port=port)
    # ... use nodriver to connect ...
    process.terminate()
"""

from .chrome import find_chrome, launch_chrome, DEFAULT_PROFILE_PREFIX
from .port import (
    is_port_in_use,
    is_temp_chrome_on_port,
    is_chrome_in_use,
    find_temp_chromes,
    get_available_port,
    DEFAULT_DEBUG_PORT,
    DEFAULT_DEBUG_HOST,
)
from .process import get_pid_on_port, get_process_cmdline, kill_process_tree

__all__ = [
    # Chrome detection and launching
    "find_chrome",
    "launch_chrome",
    "DEFAULT_PROFILE_PREFIX",
    # Port management
    "is_port_in_use",
    "is_temp_chrome_on_port",
    "is_chrome_in_use",
    "find_temp_chromes",
    "get_available_port",
    "DEFAULT_DEBUG_PORT",
    "DEFAULT_DEBUG_HOST",
    # Process management
    "get_pid_on_port",
    "get_process_cmdline",
    "kill_process_tree",
]
