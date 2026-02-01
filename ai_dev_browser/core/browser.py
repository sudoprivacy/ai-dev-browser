"""Browser lifecycle management operations."""

import time
from pathlib import Path

from .chrome import launch_chrome
from .config import DEFAULT_PROFILE_DIR, ReuseStrategy
from .port import (
    cleanup_temp_profile,
    find_ai_dev_browser_chromes,
    find_our_chromes,
    get_available_port,
    get_pid_on_port,
    is_chrome_in_use,
    is_port_in_use,
)
from .process import kill_process_tree


def _find_reusable_chrome(reuse: str) -> int | None:
    """Find a reusable Chrome based on reuse strategy.

    Args:
        reuse: "this_session", "ai_dev_browser", or "any"

    Returns:
        Port number if found, None otherwise
    """
    from .port import find_debug_chromes

    if reuse == "this_session":
        for port in find_our_chromes(exclude_in_use=False):
            if not is_chrome_in_use(port):
                return port

    elif reuse == "ai_dev_browser":
        for port in find_ai_dev_browser_chromes():
            if not is_chrome_in_use(port):
                return port

    elif reuse == "any":
        for port, _pid in find_debug_chromes():
            if not is_chrome_in_use(port):
                return port

    return None


def start_browser(
    port: int | None = None,
    headless: bool = False,
    url: str | None = None,
    profile: str | None = None,
    temp: bool = False,
    reuse: ReuseStrategy = "none",
) -> dict:
    """Start or reuse a browser instance.

    Args:
        port: Debug port (auto-assigned if None)
        headless: Run in headless mode
        url: Initial URL to open (default: about:blank)
        profile: Profile name (default: "default")
        temp: Use temporary profile instead
        reuse: Reuse strategy - none/this_session/ai_dev_browser/any

    Returns:
        dict with port, pid, headless, url, profile, reused, message
    """
    # Try to reuse existing Chrome based on reuse strategy
    if reuse != "none":
        reused_port = _find_reusable_chrome(reuse)
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

    # Determine user data directory
    if temp:
        user_data_dir = None
        profile_name = "(temp)"
    else:
        profile_name = profile or "default"
        user_data_dir = Path(DEFAULT_PROFILE_DIR) / profile_name
        user_data_dir.mkdir(parents=True, exist_ok=True)

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


def stop_browser(
    port: int | None = None,
    stop_all: bool = False,
) -> dict:
    """Stop browser instance(s).

    Args:
        port: Port of browser to stop
        stop_all: Stop all our browser instances

    Returns:
        dict with stopped status, count, browsers list
    """
    if not port and not stop_all:
        return {"error": "Please specify port or stop_all"}

    stopped = []

    if stop_all:
        ports = find_our_chromes(exclude_in_use=False)
        for p in ports:
            try:
                pid = get_pid_on_port(p)
                if pid:
                    kill_process_tree(pid)
                    cleanup_temp_profile(p)
                    stopped.append({"port": p, "pid": pid})
            except Exception:
                pass
    else:
        pid = get_pid_on_port(port)
        if pid:
            kill_process_tree(pid)
            stopped.append({"port": port, "pid": pid})

    return {
        "stopped": True,
        "count": len(stopped),
        "browsers": stopped,
    }


def list_browsers(
    mine: bool = False,
) -> dict:
    """List running ai-dev-browser Chrome instances.

    Args:
        mine: If True, only show Chromes from this session

    Returns:
        dict with browsers list and count
    """
    my_ports = set(find_our_chromes(exclude_in_use=False))

    if mine:
        browsers = []
        for p in my_ports:
            browsers.append(
                {
                    "port": p,
                    "pid": get_pid_on_port(p),
                    "can_connect": not is_chrome_in_use(p),
                }
            )
        return {"browsers": browsers, "count": len(my_ports)}

    all_ports = find_ai_dev_browser_chromes()
    this_session = []
    other_sessions = []

    for p in all_ports:
        entry = {
            "port": p,
            "pid": get_pid_on_port(p),
            "can_connect": not is_chrome_in_use(p),
        }
        if p in my_ports:
            this_session.append(entry)
        else:
            other_sessions.append(entry)

    return {
        "this_session": this_session,
        "other_sessions": other_sessions,
        "count": len(all_ports),
    }
