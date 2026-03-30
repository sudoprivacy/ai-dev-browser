"""Browser lifecycle management operations."""

import os
import time
from pathlib import Path

from .chrome import launch_chrome
from .config import DEFAULT_PROFILE_DIR, DEFAULT_REUSE_STRATEGY, ReuseStrategy
from .port import (
    _cleanup_temp_profile,
    find_debug_chromes,
    get_available_port,
    get_pid_on_port,
    is_chrome_in_use,
    is_port_in_use,
)
from .process import _find_chrome_processes, _kill_process_tree, get_process_cmdline


def _is_profile_locked(profile_dir: Path) -> bool:
    """Check if a Chrome profile is locked by another process.

    Chrome creates a 'SingletonLock' symlink when using a profile.
    Note: We check both exists() and is_symlink() because:
    - exists() returns False for broken symlinks
    - Chrome's SingletonLock is a symlink that may be broken but still indicates lock
    """
    singleton_lock = profile_dir / "SingletonLock"
    return singleton_lock.exists() or singleton_lock.is_symlink()


def _find_chrome_using_profile(profile_dir: Path) -> tuple[int, int] | None:
    """Find a debugging Chrome using the specified profile.

    Scans debug port range (9350-9450) for Chrome with matching profile dir.

    Returns:
        (port, pid) tuple if found, None otherwise
    """
    profile_str = str(profile_dir)

    for port, pid in find_debug_chromes():
        try:
            cmdline = get_process_cmdline(pid)
            if cmdline and profile_str in cmdline:
                return (port, pid)
        except Exception:
            pass

    return None


def _find_reusable_chrome() -> int | None:
    """Find an idle debugging Chrome to reuse.

    Returns:
        Port number if found, None otherwise
    """
    for port, _pid in find_debug_chromes():
        if not is_chrome_in_use(port):
            return port
    return None


def start_browser(
    port: int | None = None,
    headless: bool = os.environ.get("AI_DEV_BROWSER_HEADLESS", "").lower() in ("1", "true"),
    url: str | None = None,
    profile: str | None = None,
    temp: bool = False,
    reuse: ReuseStrategy = DEFAULT_REUSE_STRATEGY,
) -> dict:
    """Start or reuse a browser instance.

    Args:
        port: Debug port (auto-assigned if None)
        headless: Run in headless mode
        url: Initial URL to open (default: about:blank)
        profile: Profile name (default: "default")
        temp: Use temporary profile instead
        reuse: "none" (always new) or "any" (reuse idle Chrome, default)

    Returns:
        dict with port, pid, headless, url, profile, reused, message
    """
    # Try to reuse existing Chrome
    if reuse != "none":
        reused_port = _find_reusable_chrome()
        if reused_port:
            pid = get_pid_on_port(reused_port)
            return {
                "port": reused_port,
                "pid": pid,
                "reused": True,
                "message": f"Reusing existing Chrome on port {reused_port}",
            }

    # No reusable Chrome found, start new one
    if port is None:
        port = get_available_port(reuse=(reuse != "none"))
    else:
        # User specified a port - check if it's available
        if is_port_in_use(port=port):
            pid = get_pid_on_port(port)
            return {
                "error": f"Port {port} is already in use (PID: {pid}). "
                f"Use a different port or stop the existing process."
            }

    # Determine user data directory
    if temp:
        user_data_dir = None
        profile_name = "(temp)"
    else:
        profile_name = profile or "default"
        user_data_dir = Path(DEFAULT_PROFILE_DIR) / profile_name
        user_data_dir.mkdir(parents=True, exist_ok=True)

        # Always check for existing Chrome using this profile
        # Lock file may be missing even when Chrome is running (e.g., on macOS)
        existing = _find_chrome_using_profile(user_data_dir)
        if existing:
            existing_port, existing_pid = existing
            # Auto-reuse the existing Chrome with this profile
            return {
                "port": existing_port,
                "pid": existing_pid,
                "profile": profile_name,
                "reused": True,
                "message": f"Profile '{profile_name}' already in use. Reusing Chrome on port {existing_port}.",
            }

        # Check for stale lock file (lock exists but no Chrome found)
        if _is_profile_locked(user_data_dir):
            # Try to remove the stale lock and continue
            try:
                (user_data_dir / "SingletonLock").unlink()
            except Exception:
                return {
                    "error": f"Profile '{profile_name}' is locked but no Chrome found. "
                    f"Try manually removing: {user_data_dir / 'SingletonLock'}"
                }

    # Launch Chrome
    start_url = url or "about:blank"
    process = launch_chrome(
        port=port,
        headless=headless,
        start_url=start_url,
        user_data_dir=str(user_data_dir) if user_data_dir else None,
    )

    # Wait for Chrome to start listening on the port
    max_wait = 10.0
    poll_interval = 0.2
    elapsed = 0.0
    while elapsed < max_wait:
        if is_port_in_use(port=port):
            break
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr else ""
            # Provide more helpful error message
            if not stderr:
                stderr = (
                    "Chrome exited silently. Possible causes:\n"
                    "  - Another Chrome is using this profile\n"
                    "  - Profile directory is corrupted\n"
                    "  - Insufficient permissions"
                )
            return {"error": f"Chrome process exited unexpectedly: {stderr}"}
        time.sleep(poll_interval)
        elapsed += poll_interval
    else:
        return {
            "error": f"Chrome started (PID {process.pid}) but port {port} not listening after {max_wait}s",
            "pid": process.pid,
        }

    return {
        "port": port,
        "pid": process.pid,
        "headless": headless,
        "url": start_url,
        "profile": profile_name,
        "reused": False,
        "message": f"Browser started on port {port}",
    }


def _find_zombie_chromes(
    known_pids: set[int] | None = None,
) -> list[dict]:
    """Find debugging Chromes not visible via port scanning.

    These are Chrome processes that have --remote-debugging-port in their
    command line but failed to bind the port (e.g., due to Hyper-V reserved
    ports) or are listening outside our scanned range.

    Any Chrome with --remote-debugging-port is a debugging Chrome created
    by automation — regular user Chromes never have this flag.

    Args:
        known_pids: PIDs already found via port scanning (to deduplicate)

    Returns:
        List of {"pid": int} dicts for zombie Chromes.
    """
    known_pids = known_pids or set()
    zombies = []

    for pid, cmdline in _find_chrome_processes():
        if pid in known_pids:
            continue
        # Any Chrome with --remote-debugging-port is a debugging Chrome
        if "--remote-debugging-port" not in cmdline:
            continue
        # Skip renderer/gpu/utility child processes — only main process matters
        if "--type=" in cmdline:
            continue
        zombies.append({"pid": pid})

    return zombies


def stop_browser(
    port: int | None = None,
    stop_all: bool = False,
) -> dict:
    """Stop browser instance(s).

    Args:
        port: Port of browser to stop
        stop_all: Stop all debugging Chrome instances (port-bound + zombies)

    Returns:
        dict with stopped status, count, browsers list
    """
    if not port and not stop_all:
        return {"error": "Please specify port or stop_all"}

    stopped = []

    if stop_all:
        known_pids = set()
        # Kill all debugging Chromes found via port scanning
        for p, pid in find_debug_chromes():
            try:
                known_pids.add(pid)
                _kill_process_tree(pid)
                _cleanup_temp_profile(p)
                stopped.append({"port": p, "pid": pid})
            except Exception:
                pass

        # Also kill zombie Chromes (no port bound but process exists)
        for zombie in _find_zombie_chromes(known_pids):
            _kill_process_tree(zombie["pid"])
            stopped.append({"port": None, "pid": zombie["pid"], "zombie": True})
    else:
        pid = get_pid_on_port(port)
        if pid:
            _kill_process_tree(pid)
            stopped.append({"port": port, "pid": pid})

    return {
        "stopped": True,
        "count": len(stopped),
        "browsers": stopped,
    }


def list_browsers() -> dict:
    """List all debugging Chrome instances.

    Combines port-based discovery (working Chromes) with process-based
    discovery (zombie Chromes that failed to bind their debug port).

    Any Chrome with --remote-debugging-port is a debugging Chrome created
    by automation — regular user Chromes never have this flag.

    Returns:
        dict with browsers list and count
    """
    browsers = []
    known_pids = set()

    # Port-based discovery (Chromes listening on debug ports)
    for p, pid in find_debug_chromes():
        known_pids.add(pid)
        browsers.append(
            {
                "port": p,
                "pid": pid,
                "can_connect": not is_chrome_in_use(p),
            }
        )

    # Process-based discovery (zombie Chromes)
    for zombie in _find_zombie_chromes(known_pids):
        browsers.append(
            {
                "port": None,
                "pid": zombie["pid"],
                "can_connect": False,
                "zombie": True,
            }
        )

    return {
        "browsers": browsers,
        "count": len(browsers),
    }
