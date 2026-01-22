"""Shared configuration constants for ai-dev-browser.

All paths and prefixes are defined here to avoid duplication.
Both tools/ and package code should import from this module.
"""

from pathlib import Path
from typing import Literal

# TODO(temp): Remove after macOS migration - 2025-01-23
_old_dir = Path("~/.nodriver-kit").expanduser()
if _old_dir.exists():
    print(f"[ai-dev-browser] Legacy dir found: {_old_dir}")
    print(f"[ai-dev-browser] Run: mv ~/.nodriver-kit ~/.ai-dev-browser")

# Base directory for all ai-dev-browser data
DEFAULT_BASE_DIR = Path("~/.ai-dev-browser").expanduser()

# Profile directories
DEFAULT_PROFILE_DIR = DEFAULT_BASE_DIR / "profiles"

# Cookie files
DEFAULT_COOKIES_FILE = DEFAULT_BASE_DIR / "cookies.dat"
DEFAULT_COOKIES_DIR = DEFAULT_BASE_DIR / "cookies"

# Temp profile prefix (used to identify our Chrome instances)
DEFAULT_PROFILE_PREFIX = "nodriver_chrome_"

# Debug port range
DEFAULT_DEBUG_HOST = "127.0.0.1"
DEFAULT_DEBUG_PORT = 9222
DEFAULT_PORT_RANGE = (9222, 9300)

# Browser reuse strategy
# - none: Always start new Chrome
# - this_session: Reuse Chrome from current ai-dev-browser session only
# - ai_dev_browser: Reuse any ai-dev-browser Chrome (including from previous runs)
# - any: Reuse any debugging Chrome
ReuseStrategy = Literal["none", "this_session", "ai_dev_browser", "any"]
DEFAULT_REUSE_STRATEGY: ReuseStrategy = "none"
