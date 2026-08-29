"""Orphan Chrome cleanup for ai-dev-browser-managed profiles.

Long sessions with `close_chrome=False` accumulate Chrome processes
(main + helper/renderer children) holding `--user-data-dir` locks on
our managed profile directories. When the next `browser_start` tries
to launch a fresh Chrome on the same profile, the lockfile contention
causes the new spawn to fail. `browser_cleanup` scans for and kills
the orphans.

`psutil` is the only reliable cross-platform way to read every
chrome.exe's command line; we make it an optional extra so users who
never need cleanup don't pay the install cost.
"""

import logging
import os
from pathlib import Path

from .config import (
    DEFAULT_PROFILE_DIR,
    DEFAULT_PROFILE_PREFIX,
    get_workspace_profile_dir,
)
from .port import _query_chrome_user_data_dir, find_debug_chromes
from .process import _kill_process_tree


logger = logging.getLogger(__name__)


def _normalize_path(path: str) -> str:
    """Normalize a path for comparison (resolves separators + Windows case)."""
    return os.path.normcase(os.path.normpath(path))


def _is_managed_profile(user_data_dir_normalized: str) -> bool:
    """True iff the user_data_dir is inside our managed namespace.

    Two namespaces:
      - Workspace profiles: under `DEFAULT_PROFILE_DIR`
        (`~/.ai-dev-browser/profiles/...`)
      - Temp profiles: directory name starts with `DEFAULT_PROFILE_PREFIX`
        (`ai_dev_browser_<port>` in the system temp dir)
    """
    workspace_root = _normalize_path(str(DEFAULT_PROFILE_DIR))
    if user_data_dir_normalized.startswith(workspace_root):
        return True
    name = Path(user_data_dir_normalized).name
    return name.startswith(DEFAULT_PROFILE_PREFIX)


def browser_cleanup(profile: str | None = None) -> dict:
    """Use when: long sessions with `close_chrome=False` accumulated
    orphan chrome.exe processes that hold workspace profile dir locks,
    blocking new `browser_start` calls (typical symptom on Windows:
    `browser_start` errors with "started but port not listening" even
    after raising `startup_timeout`).

    Scans every chrome.exe whose `--user-data-dir` argument points
    into our managed profile namespace, then kills the process tree
    of any whose user-data-dir has no live debug-ready Chrome owner.
    Live Chromes (visible to `find_debug_chromes`) are left alone.

    Returns `{killed, count, profile_dirs}` so you can verify what was
    cleaned. Safe by construction — never touches Chrome processes
    outside `~/.ai-dev-browser/profiles/...` or the temp profile
    prefix `ai_dev_browser_*`.

    Args:
        profile: Workspace profile name to scope cleanup to. None →
            all managed profiles for the current workspace + any
            temp profiles in our namespace.

    Returns:
        dict with `killed` (list of PIDs), `count` (len of killed),
        and `profile_dirs` (sorted list of user-data-dirs that had
        orphans cleaned).

    Failure:
        Requires the `cleanup` extra for `psutil`. Install via:
        `pip install 'ai-dev-browser[cleanup]'`. After install, retry.
    """
    try:
        import psutil
    except ImportError as e:
        raise ImportError(
            "browser_cleanup requires psutil. Install via: "
            "pip install 'ai-dev-browser[cleanup]'"
        ) from e

    # 1. Snapshot user_data_dirs of currently live debug-ready Chromes.
    #    These are NOT orphans — their lifecycle is owned by whoever
    #    launched them, and killing them would surprise the caller.
    #    The user-data-dir comes from the instance registry (with a CDP
    #    cmdline fallback) — NOT Browser.getBrowserCommandLine directly,
    #    which returns nothing under stealth and would leave alive_dirs
    #    empty, making this treat every live managed Chrome as an orphan.
    alive_dirs: set[str] = set()
    for port, _pid, _ws in find_debug_chromes():
        alive_udd = _query_chrome_user_data_dir(port)
        if alive_udd:
            alive_dirs.add(_normalize_path(alive_udd))

    # 2. Optional single-profile filter.
    profile_filter: str | None = None
    if profile:
        profile_filter = _normalize_path(str(get_workspace_profile_dir(profile)))

    # 3. Enumerate chrome processes; kill orphans whose --user-data-dir
    #    is in our namespace and has no live debug owner.
    killed: list[int] = []
    profile_dirs_cleaned: set[str] = set()

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if "chrome" not in name:
                continue
            cmdline = proc.info.get("cmdline") or []
            udd: str | None = None
            for arg in cmdline:
                if arg.startswith("--user-data-dir="):
                    udd = _normalize_path(arg.split("=", 1)[1])
                    break
            if not udd:
                # Helper / renderer subprocess inherits user-data-dir
                # implicitly — _kill_process_tree on the main parent
                # below catches these. Skip standalone matching here.
                continue
            if not _is_managed_profile(udd):
                continue
            if profile_filter and udd != profile_filter:
                continue
            if udd in alive_dirs:
                continue  # debug-ready owner exists, not an orphan

            pid = proc.info["pid"]
            if _kill_process_tree(pid):
                killed.append(pid)
                profile_dirs_cleaned.add(udd)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Process vanished mid-iteration or we lack rights — skip.
            continue

    return {
        "killed": killed,
        "count": len(killed),
        "profile_dirs": sorted(profile_dirs_cleaned),
    }
