"""Shared configuration constants for nodriver-kit.

All paths and prefixes are defined here to avoid duplication.
Both tools/ and package code should import from this module.
"""

from pathlib import Path

# Base directory for all nodriver-kit data
DEFAULT_BASE_DIR = Path("~/.nodriver-kit").expanduser()

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
