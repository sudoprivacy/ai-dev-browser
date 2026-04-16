"""Browser lifecycle management operations."""

import asyncio
import os
import time
from pathlib import Path

from .chrome import launch_chrome
from .config import (
    DEFAULT_REUSE_STRATEGY,
    ReuseStrategy,
    get_workspace_profile_dir,
)
from .connection import graceful_close_browser
from .port import (
    _cleanup_temp_profile,
    _query_chrome_cmdline,
    find_debug_chromes,
    find_workspace_chromes,
    get_available_port,
    get_pid_on_port,
    is_port_in_use,
)
from .process import _kill_process_tree


def _find_chrome_using_profile(profile_dir: Path) -> tuple[int, int | None] | None:
    """Find a debugging Chrome using the specified profile via CDP.

    Scans debug port range and queries each Chrome's command line
    to check if --user-data-dir matches the given profile directory.

    Returns:
        (port, pid) tuple if found, None otherwise.
    """
    profile_str = str(profile_dir)
    for port, pid, _ws in find_debug_chromes():
        cmdline = _query_chrome_cmdline(port)
        if cmdline and any(profile_str in arg for arg in cmdline):
            return (port, pid)
    return None


def _find_reusable_chrome() -> int | None:
    """Find a debugging Chrome in the current workspace to reuse.

    Returns:
        Port number if found, None otherwise
    """
    for port, _pid in find_workspace_chromes():
        return port
    return None


def browser_start(
    port: int | None = None,
    headless: bool = os.environ.get("AI_DEV_BROWSER_HEADLESS", "").lower()
    in ("1", "true"),
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
        user_data_dir = get_workspace_profile_dir(profile_name)
        user_data_dir.mkdir(parents=True, exist_ok=True)

        # Safety: if another Chrome is already using this profile, reuse it
        # (launching two Chromes with the same user-data-dir causes crashes)
        existing = _find_chrome_using_profile(user_data_dir)
        if existing:
            existing_port, existing_pid = existing
            return {
                "port": existing_port,
                "pid": existing_pid,
                "profile": profile_name,
                "reused": True,
                "message": f"Profile '{profile_name}' already in use. Reusing Chrome on port {existing_port}.",
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


def _graceful_stop(port: int, pid: int, timeout: float = 5.0) -> dict:
    """Gracefully stop a Chrome instance via CDP Browser.close().

    Sends Browser.close() which flushes cookies/profile data, then waits
    for the process to exit. Falls back to force-kill if graceful fails.

    Returns:
        dict with port, pid, and method used ("graceful" or "force").
    """
    # Try graceful shutdown via CDP
    try:
        sent = asyncio.run(graceful_close_browser(port=port))
    except RuntimeError:
        # Already inside a running event loop — use a thread with its own loop
        import concurrent.futures

        def _run_close():
            return asyncio.run(graceful_close_browser(port=port))

        try:
            with concurrent.futures.ThreadPoolExecutor() as pool:
                sent = pool.submit(_run_close).result(timeout=timeout)
        except Exception:
            sent = False
    except Exception:
        sent = False

    if sent:
        # Wait for process to exit
        elapsed = 0.0
        poll_interval = 0.2
        while elapsed < timeout:
            if not is_port_in_use(port=port):
                _cleanup_temp_profile(port)
                return {"port": port, "pid": pid, "method": "graceful"}
            time.sleep(poll_interval)
            elapsed += poll_interval

    # Graceful failed or timed out — force kill
    _kill_process_tree(pid)
    _cleanup_temp_profile(port)
    return {"port": port, "pid": pid, "method": "force"}


def browser_stop(
    port: int | None = None,
    stop_all: bool = False,
) -> dict:
    """Stop browser instance(s).

    Uses CDP Browser.close() for graceful shutdown (flushes cookies to
    profile SQLite). Falls back to force-kill if graceful fails.

    Args:
        port: Port of browser to stop
        stop_all: Stop all debugging Chrome instances

    Returns:
        dict with stopped status, count, browsers list
    """
    if not port and not stop_all:
        return {"error": "Please specify port or stop_all"}

    stopped = []

    if stop_all:
        for p, pid, _ws in find_debug_chromes():
            if pid is None:
                continue
            try:
                result = _graceful_stop(p, pid)
                stopped.append(result)
            except Exception:
                pass
    else:
        pid = get_pid_on_port(port)
        if pid:
            result = _graceful_stop(port, pid)
            stopped.append(result)

    return {
        "stopped": True,
        "count": len(stopped),
        "browsers": stopped,
    }


def browser_list(all_workspaces: bool = False) -> dict:
    """List debugging Chrome instances.

    By default, shows only Chromes belonging to the current workspace.
    Use all_workspaces=True to see all debugging Chromes.

    Args:
        all_workspaces: Show Chromes from all workspaces (default: current only)

    Returns:
        dict with browsers list and count
    """
    browsers = []

    if all_workspaces:
        for p, pid, workspace in find_debug_chromes():
            info: dict = {
                "port": p,
                "pid": pid,
            }
            if workspace:
                info["workspace"] = workspace
            browsers.append(info)
    else:
        for p, pid in find_workspace_chromes():
            browsers.append(
                {
                    "port": p,
                    "pid": pid,
                }
            )

    return {
        "browsers": browsers,
        "count": len(browsers),
    }
