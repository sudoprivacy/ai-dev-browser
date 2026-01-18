"""Port management for Chrome debugging.

This module provides port scanning and availability detection:
- is_port_in_use: Check if a port is occupied
- get_available_port: Find an available debugging port
- is_our_chrome_on_port: Check if Chrome was started by this session
- find_our_chromes: Find Chrome instances started by this session

The port management uses session ID tagging to identify which Chrome instances
were started by this nodriver-kit process.

Example:
    port = get_available_port()
    print(f"Available port: {port}")
"""

import json
import logging
import shutil
import socket
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from .config import DEFAULT_DEBUG_HOST, DEFAULT_DEBUG_PORT, DEFAULT_PORT_RANGE, DEFAULT_PROFILE_PREFIX
from .process import get_pid_on_port, get_process_cmdline
from .session import is_our_session, get_session_id, SESSION_FLAG

logger = logging.getLogger(__name__)


# =============================================================================
# Shared Helpers (DRY)
# =============================================================================


def _is_chrome_process(cmdline: str | None) -> bool:
    """Check if cmdline indicates a Chrome process."""
    return cmdline is not None and "chrome" in cmdline.lower()


def _get_chrome_info_on_port(port: int) -> tuple[int | None, str | None]:
    """Get PID and cmdline for process on port.

    Returns:
        Tuple of (pid, cmdline). Both None if no process found.
    """
    pid = get_pid_on_port(port)
    if pid is None:
        return None, None
    cmdline = get_process_cmdline(pid)
    return pid, cmdline


def _scan_ports(
    port_range: tuple[int, int],
    predicate,
    exclude: set[int] | None = None,
    check_in_use: bool = False,
    exclude_in_use: bool = False,
    return_first: bool = False,
) -> list[int] | int | None:
    """Scan ports with a predicate function.

    Args:
        port_range: (start, end) tuple
        predicate: Function(port) -> bool, called for each port
        exclude: Ports to skip
        check_in_use: If True, only scan ports that are in use
        exclude_in_use: If True, skip ports where Chrome has attached debugger
        return_first: If True, return first match instead of list

    Returns:
        List of matching ports, or first match if return_first=True
    """
    exclude = exclude or set()
    results = []

    for port in range(port_range[0], port_range[1]):
        if port in exclude:
            continue

        # Check if port is in use (if required)
        if check_in_use and not is_port_in_use(DEFAULT_DEBUG_HOST, port):
            continue

        # Apply predicate
        if not predicate(port):
            continue

        # Check CDP in-use status
        if exclude_in_use and is_chrome_in_use(port):
            logger.debug(f"Skipping in-use Chrome on port {port}")
            continue

        if return_first:
            return port
        results.append(port)

    return None if return_first else results


# =============================================================================
# Port Detection
# =============================================================================


def is_port_in_use(host: str = DEFAULT_DEBUG_HOST, port: int = DEFAULT_DEBUG_PORT, timeout: float = 0.1) -> bool:
    """
    Check if a port is in use (Chrome might be listening).

    Checks both IPv4 and IPv6 (Chrome on Windows might only listen on IPv6).

    Args:
        host: Host to check (default: 127.0.0.1)
        port: Port to check (default: 9222)
        timeout: Connection timeout in seconds (default 0.1s for fast scanning)

    Returns:
        True if port is in use, False otherwise.

    Example:
        if is_port_in_use(port=9222):
            print("Chrome already running on 9222")
    """
    # Check IPv4
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect((host, port))
            return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        pass

    # Check IPv6 (Chrome on Windows might only listen on IPv6)
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            # Map IPv4 loopback to IPv6
            ipv6_host = "::1" if host in ("127.0.0.1", "localhost") else host
            sock.connect((ipv6_host, port))
            return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        pass

    return False


def is_our_chrome_on_port(port: int) -> tuple[bool, int | None]:
    """
    Check if the Chrome on a port was started by THIS nodriver-kit session.

    Uses session ID tagging (more reliable than profile prefix matching).
    Each nodriver-kit process gets a unique session ID injected into Chrome's
    command line as --nodriver-kit-session=<id>.

    Args:
        port: Port to check

    Returns:
        Tuple of (is_our_chrome, pid). If not our Chrome or no Chrome, returns (False, None).

    Example:
        is_ours, pid = is_our_chrome_on_port(9222)
        if is_ours:
            print(f"This Chrome was started by us, PID: {pid}")
    """
    pid, cmdline = _get_chrome_info_on_port(port)
    if pid is None:
        return False, None
    if not _is_chrome_process(cmdline):
        return False, pid

    # Check if it's our session
    if is_our_session(cmdline):
        return True, pid

    return False, pid


def is_nodriver_kit_chrome_on_port(port: int) -> tuple[bool, int | None]:
    """
    Check if the Chrome on a port was started by ANY nodriver-kit process.

    Unlike is_our_chrome_on_port(), this checks for the session flag presence
    (not matching value), so it finds Chromes from previous runs too.

    Args:
        port: Port to check

    Returns:
        Tuple of (is_nodriver_kit_chrome, pid). If not nodriver-kit Chrome, returns (False, None).

    Example:
        is_ndk, pid = is_nodriver_kit_chrome_on_port(9222)
        if is_ndk:
            print(f"This Chrome was started by nodriver-kit, PID: {pid}")
    """
    pid, cmdline = _get_chrome_info_on_port(port)
    if pid is None:
        return False, None
    if not _is_chrome_process(cmdline):
        return False, pid

    # Check for nodriver-kit session flag (any session)
    if SESSION_FLAG in cmdline:
        return True, pid

    return False, pid


def find_our_chromes(
    port_range: tuple[int, int] = DEFAULT_PORT_RANGE,
    exclude_in_use: bool = True,
) -> list[int]:
    """
    Find all Chrome instances started by THIS nodriver-kit session.

    Uses session ID tagging to identify our Chromes. More reliable than
    profile prefix matching because it distinguishes between different
    nodriver-kit processes running simultaneously.

    Args:
        port_range: Tuple of (start_port, end_port) to scan
        exclude_in_use: If True (default), skip ports where Chrome has attached
                       debugger sessions (detected via CDP).

    Returns:
        List of ports with our Chrome instances.

    Example:
        ports = find_our_chromes()
        print(f"Found {len(ports)} Chrome instances from this session")
    """
    def is_our_chrome(port: int) -> bool:
        is_ours, _ = is_our_chrome_on_port(port)
        return is_ours

    return _scan_ports(port_range, is_our_chrome, exclude_in_use=exclude_in_use)


def is_chrome_in_use(port: int, timeout: float = 0.5) -> bool:
    """
    Check if Chrome on this port is being used by another script via CDP.

    This is more reliable than file-based locking because:
    1. No cleanup needed - when script dies, CDP attachment is automatically released
    2. No race conditions - CDP state is always current
    3. No stale lock detection needed

    Args:
        port: Chrome debugging port to check
        timeout: Connection timeout in seconds

    Returns:
        True if Chrome has attached debugger sessions (in use by another script),
        False if no attached sessions or Chrome is not available.

    Example:
        if is_chrome_in_use(9222):
            print("Chrome on 9222 is busy, find another port")
    """
    try:
        # Get browser WebSocket URL
        version_url = f"http://127.0.0.1:{port}/json/version"
        req = urllib.request.Request(version_url)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            version = json.loads(response.read())
            browser_ws = version.get("webSocketDebuggerUrl")

        if not browser_ws:
            return False

        # Use synchronous WebSocket to check targets
        import websocket

        ws = websocket.create_connection(browser_ws, timeout=timeout)
        try:
            # Get all targets
            ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
            response = json.loads(ws.recv())

            # Check if any page targets are attached
            for target in response.get("result", {}).get("targetInfos", []):
                if target.get("type") == "page" and target.get("attached", False):
                    logger.debug(
                        f"Port {port} is in use: page '{target.get('title', 'unknown')[:30]}' "
                        f"has attached debugger"
                    )
                    return True

            return False
        finally:
            ws.close()

    except Exception as e:
        logger.debug(f"Could not check CDP state for port {port}: {e}")
        return False


def get_available_port(
    start: int = 9222,
    end: int = 9300,
    exclude: set[int] | None = None,
) -> int:
    """
    Find an available port for Chrome, preferring to reuse existing instances.

    Port selection strategy:
    1. First, look for existing Chrome from THIS session not in use
    2. Then, look for ANY nodriver-kit Chrome (from previous runs) not in use
    3. If none found, find an unused port for launching new Chrome

    This strategy preserves login sessions and reduces startup time.

    Args:
        start: Start of port range to search (default: 9222)
        end: End of port range to search (default: 9300)
        exclude: Set of ports to skip (e.g., already assigned to workers)

    Returns:
        An available port number

    Raises:
        RuntimeError: If no available port found in range

    Example:
        port = get_available_port(exclude={9222, 9223})
        print(f"Use port {port}")
    """
    port_range = (start, end)

    # Strategy 1: Reuse Chrome from our session (not in use)
    def is_our_available_chrome(port: int) -> bool:
        is_ours, _ = is_our_chrome_on_port(port)
        if is_ours and not is_chrome_in_use(port):
            logger.debug(f"Found reusable Chrome from our session on port {port}")
            return True
        return False

    port = _scan_ports(port_range, is_our_available_chrome, exclude=exclude,
                       check_in_use=True, return_first=True)
    if port is not None:
        return port

    # Strategy 2: Reuse ANY nodriver-kit Chrome (not in use)
    def is_ndk_available_chrome(port: int) -> bool:
        is_ndk, _ = is_nodriver_kit_chrome_on_port(port)
        if is_ndk and not is_chrome_in_use(port):
            logger.debug(f"Found reusable nodriver-kit Chrome (from previous run) on port {port}")
            return True
        return False

    port = _scan_ports(port_range, is_ndk_available_chrome, exclude=exclude,
                       check_in_use=True, return_first=True)
    if port is not None:
        return port

    # Strategy 3: Find unused port
    def is_unused_port(port: int) -> bool:
        return not is_port_in_use(DEFAULT_DEBUG_HOST, port)

    port = _scan_ports(port_range, is_unused_port, exclude=exclude, return_first=True)
    if port is not None:
        return port

    raise RuntimeError(f"No available port found in range {start}-{end}")


def find_nodriver_kit_chromes(
    port_range: tuple[int, int] = DEFAULT_PORT_RANGE,
    exclude_in_use: bool = False,
) -> list[int]:
    """
    Find all Chrome instances started by ANY nodriver-kit process.

    Unlike find_our_chromes() which only finds current session's Chromes,
    this finds Chromes from all nodriver-kit sessions (but NOT user-started Chromes).

    Args:
        port_range: Tuple of (start_port, end_port) to scan
        exclude_in_use: If True, skip ports with attached debugger sessions

    Returns:
        List of ports with nodriver-kit Chrome instances
    """
    def is_ndk_chrome(port: int) -> bool:
        is_ndk, _ = is_nodriver_kit_chrome_on_port(port)
        return is_ndk

    return _scan_ports(port_range, is_ndk_chrome, exclude_in_use=exclude_in_use)


def find_debug_chromes(
    port_range: tuple[int, int] = DEFAULT_PORT_RANGE,
) -> list[tuple[int, int]]:
    """
    Find all Chrome instances listening on debug ports.

    This finds ALL Chromes regardless of who started them.
    Useful for browser_stop --all to clean up any debug Chrome.

    Args:
        port_range: Tuple of (start_port, end_port) to scan

    Returns:
        List of (port, pid) tuples for each found Chrome
    """
    chromes = []

    def collect_chrome(port: int) -> bool:
        pid, cmdline = _get_chrome_info_on_port(port)
        if pid and _is_chrome_process(cmdline):
            chromes.append((port, pid))
        return False  # Always continue scanning

    _scan_ports(port_range, collect_chrome, check_in_use=True)
    return chromes


def cleanup_temp_profile(
    port: int,
    profile_prefix: str = DEFAULT_PROFILE_PREFIX,
) -> bool:
    """
    Clean up temp profile directory for a port if it exists.

    Args:
        port: The port number (used to construct temp dir name)
        profile_prefix: Profile directory prefix

    Returns:
        True if profile was cleaned up, False otherwise
    """
    temp_dir = Path(tempfile.gettempdir()) / f"{profile_prefix}{port}"
    if temp_dir.exists():
        try:
            shutil.rmtree(temp_dir)
            logger.debug(f"Cleaned up temp profile: {temp_dir}")
            return True
        except Exception as e:
            logger.warning(f"Failed to clean up temp profile {temp_dir}: {e}")
    return False
