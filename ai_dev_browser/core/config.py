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

# Default output directory (relative to cwd — follows the consuming project)
DEFAULT_OUTPUT_DIR = Path("output")

# Env var for consumers to inject a persistent output directory, so LLMs don't
# have to learn host-specific scratch/persistent conventions.
OUTPUT_DIR_ENV = "AI_DEV_BROWSER_OUTPUT_DIR"

# Env var pinning which page target every tool acts on, as a URL substring.
# For a browser with one tab this is unnecessary; for one with several page
# targets (Electron windows, a many-tab Chrome) it replaces a guess — see
# `connection.get_active_tab`. Process-wide, so a consumer sets it once instead
# of passing --tab-url to every call.
TAB_URL_ENV = "AI_DEV_BROWSER_TAB_URL"


def resolve_output_dir() -> Path:
    """Directory that file-producing tools write to when `path` is omitted.

    Order: `AI_DEV_BROWSER_OUTPUT_DIR` → `DEFAULT_OUTPUT_DIR` (./output/).

    Every tool that saves a file resolves it through here. It used to live in
    page.py, which meant `screenshot_by_ref` — over in ax.py — reached for
    `DEFAULT_OUTPUT_DIR` directly and silently ignored the env var its sibling
    screenshot tool honoured.
    """
    env_dir = os.environ.get(OUTPUT_DIR_ENV)
    if env_dir:
        return Path(env_dir).expanduser()
    return DEFAULT_OUTPUT_DIR


# Default render viewport, applied to every tab (see connection.get_active_tab).
# Responsive web apps switch to a mobile / compact layout below a ~768px
# breakpoint — hiding desktop navigation, toolbars, search, and exports — so a
# small default viewport silently breaks automation on enterprise apps (ERPs,
# government portals). The lever is the RENDER viewport
# (Emulation.setDeviceMetricsOverride), not the OS window: the window can't
# exceed a small virtual display, but the render viewport can. 1600x950 is a
# comfortable desktop size at deviceScaleFactor 1 (crisp, 1:1 screenshots).
DEFAULT_VIEWPORT_WIDTH = 1600
DEFAULT_VIEWPORT_HEIGHT = 950

# Width at/above which a tab is already "desktop" and its viewport is left
# untouched on acquisition. Below it the tab is in mobile/compact territory and
# gets the desktop viewport. This makes the default idempotent (a tab acquired
# twice isn't re-laid-out), lets an explicit `window_set` to a desktop width
# persist across independent CLI commands, and still guarantees a tab is never
# left in a mobile layout. 1000px sits above the common ~768px mobile
# breakpoint and below every desktop viewport we'd set.
DESKTOP_MIN_WIDTH = 1000

# Override or disable the default viewport process-wide, so a consumer sets it
# once instead of passing it to every call. "WIDTHxHEIGHT" (e.g. "1440x900")
# resizes; "native" / "off" leaves Chrome's own viewport untouched.
VIEWPORT_ENV = "AI_DEV_BROWSER_VIEWPORT"


def resolve_viewport() -> tuple[int, int] | None:
    """Render viewport `(width, height)` applied to every tab, or None to leave
    Chrome's native viewport untouched.

    Order: `AI_DEV_BROWSER_VIEWPORT` env → (`DEFAULT_VIEWPORT_WIDTH`,
    `DEFAULT_VIEWPORT_HEIGHT`). The env takes `WxH` to resize or
    `native` / `off` / `0` to disable. A malformed value raises rather than
    silently falling back — an explicitly-set viewport that's ignored would be
    the worst outcome.
    """
    raw = os.environ.get(VIEWPORT_ENV, "").strip().lower()
    if not raw:
        return DEFAULT_VIEWPORT_WIDTH, DEFAULT_VIEWPORT_HEIGHT
    if raw in ("native", "off", "0", "none", "false"):
        return None
    match = re.fullmatch(r"(\d+)\s*[x*×]\s*(\d+)", raw)
    if not match:
        raise ValueError(
            f"{VIEWPORT_ENV}={raw!r} is invalid — expected 'WIDTHxHEIGHT' "
            "(e.g. '1600x950') or 'native' to disable"
        )
    return int(match.group(1)), int(match.group(2))


# Debug port range for scanning and allocation
DEFAULT_DEBUG_HOST = "127.0.0.1"
DEFAULT_DEBUG_PORT = 9350
DEFAULT_PORT_RANGE = (9350, 9450)

# OS ephemeral / dynamic port range — scanned by the slow-path tier of
# find_debug_chromes() when the preferred range turns up empty.
#
# The OS's dynamic port range varies by platform and configuration:
#   - Linux default:   32768-60999
#   - macOS default:   49152-65535
#   - Windows default: 49152-65535, but Windows Server / custom setups
#                      can start as low as 1024 (seen in the wild)
#
# Using (1024, 65536) is a superset that covers every real-world setting,
# so bind(0) fallback ports are always discoverable. Scan cost is kept
# sane by parallelism + short timeouts in _scan_ports_for_chrome().
DEFAULT_EPHEMERAL_RANGE = (1024, 65536)

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
