"""Shared configuration constants for ai-dev-browser.

All paths and prefixes are defined here to avoid duplication.
Both tools/ and package code should import from this module.
"""

import hashlib
import os
import re
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
DEFAULT_PROFILE_PREFIX = "ai_dev_browser_"

# Screenshots (relative to cwd — follows the consuming project)
DEFAULT_SCREENSHOT_DIR = Path("screenshots")

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


def get_workspace_slug(workspace: str | None = None) -> str:
    """Convert a workspace path into a filesystem-safe slug.

    Replaces path separators and special chars with '_', truncates to 60 chars,
    and appends a short hash for uniqueness.

    E.g. /home/user/project-a → home_user_project-a_a1b2c3

    Args:
        workspace: Absolute path. Defaults to os.getcwd().
    """
    workspace = workspace or os.getcwd()
    # Normalize: resolve symlinks, case-fold on Windows
    normalized = os.path.normcase(os.path.normpath(workspace))
    # Strip drive letter colon on Windows (C:\... → C\...)
    cleaned = normalized.replace(":", "")
    # Replace path separators and non-alphanumeric (except - and .) with _
    slug = re.sub(r"[^a-zA-Z0-9\-.]", "_", cleaned).strip("_")
    # Truncate and append short hash for uniqueness
    short_hash = hashlib.sha256(normalized.encode()).hexdigest()[:6]
    if len(slug) > 60:
        slug = slug[:60].rstrip("_")
    return f"{slug}_{short_hash}"


def get_workspace_profile_dir(
    profile_name: str = "default",
    workspace: str | None = None,
) -> Path:
    """Get the profile directory for a workspace.

    Profiles are isolated per workspace:
      ~/.ai-dev-browser/profiles/{workspace_slug}/{profile_name}

    Args:
        profile_name: Profile name within the workspace.
        workspace: Workspace path. Defaults to os.getcwd().
    """
    slug = get_workspace_slug(workspace)
    return DEFAULT_PROFILE_DIR / slug / profile_name
