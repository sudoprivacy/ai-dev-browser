"""Shared configuration constants for ai-dev-browser.

All paths and prefixes are defined here to avoid duplication.
Both tools/ and package code should import from this module.
"""

from pathlib import Path
from typing import Literal


# Base directory for all ai-dev-browser data
DEFAULT_BASE_DIR = Path("~/.ai-dev-browser").expanduser()

# Profile directories
DEFAULT_PROFILE_DIR = DEFAULT_BASE_DIR / "profiles"

# Cookie files
DEFAULT_COOKIES_FILE = DEFAULT_BASE_DIR / "cookies.dat"
DEFAULT_COOKIES_DIR = DEFAULT_BASE_DIR / "cookies"

# Temp profile prefix (used to identify our Chrome instances)
DEFAULT_PROFILE_PREFIX = "nodriver_chrome_"

# Screenshots
DEFAULT_SCREENSHOT_DIR = DEFAULT_BASE_DIR / "screenshots"

# Debug port range
# Note: Windows Hyper-V reserves dynamic port ranges that change on reboot.
# get_available_port() uses _is_port_bindable() to skip reserved ports at runtime.
DEFAULT_DEBUG_HOST = "127.0.0.1"
DEFAULT_DEBUG_PORT = 9350
DEFAULT_PORT_RANGE = (9350, 9450)

# Browser reuse strategy
# - none: Always start new Chrome
# - any: Reuse any idle debugging Chrome
ReuseStrategy = Literal["none", "any"]
DEFAULT_REUSE_STRATEGY: ReuseStrategy = "any"
