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
from .session import is_our_session, get_session_id

logger = logging.getLogger(__name__)


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
    pid = get_pid_on_port(port)
    if pid is None:
        return False, None

    cmdline = get_process_cmdline(pid)
    if cmdline is None:
        return False, pid

    # Check if it's Chrome with our session ID
    if "chrome" in cmdline.lower() and is_our_session(cmdline):
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
    our_ports = []
    for port in range(port_range[0], port_range[1]):
        is_ours, _ = is_our_chrome_on_port(port)
        if is_ours:
            if exclude_in_use:
                if is_chrome_in_use(port):
                    logger.debug(f"Skipping in-use Chrome on port {port}")
                    continue
            our_ports.append(port)
    return our_ports


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
    2. If none found, find an unused port for launching new Chrome

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
    exclude = exclude or set()

    # Strategy 1: Try to reuse existing Chrome from our session not in use
    for port in range(start, end):
        if port in exclude:
            continue
        if is_port_in_use(DEFAULT_DEBUG_HOST, port):
            is_ours, _ = is_our_chrome_on_port(port)
            if is_ours and not is_chrome_in_use(port):
                logger.debug(f"Found reusable Chrome from our session on port {port}")
                return port

    # Strategy 2: Find unused port for new Chrome
    for port in range(start, end):
        if port in exclude:
            continue
        if not is_port_in_use(DEFAULT_DEBUG_HOST, port):
            return port

    raise RuntimeError(f"No available port found in range {start}-{end}")


def find_debug_chromes(
    port_range: tuple[int, int] = DEFAULT_PORT_RANGE,
) -> list[tuple[int, int]]:
    """
    Find all Chrome instances listening on debug ports.

    This finds ALL Chromes regardless of session ID.
    Useful for browser_stop --all to clean up any debug Chrome.

    Args:
        port_range: Tuple of (start_port, end_port) to scan

    Returns:
        List of (port, pid) tuples for each found Chrome
    """
    chromes = []
    for port in range(port_range[0], port_range[1]):
        if is_port_in_use(DEFAULT_DEBUG_HOST, port):
            pid = get_pid_on_port(port)
            if pid:
                chromes.append((port, pid))
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
