"""Port management for Chrome debugging.

This module provides port scanning and availability detection:
- is_port_in_use: Check if a port is occupied
- get_available_port: Find an available debugging port
- find_temp_chromes: Find Chrome instances launched by this library

The port management strategy prioritizes reusing existing Chrome instances
over launching new ones, which preserves login sessions and reduces startup time.

Example:
    port = get_available_port()
    print(f"Available port: {port}")
"""

import json
import logging
import socket
import urllib.error
import urllib.request

from .process import get_process_cmdline, get_pid_on_port

logger = logging.getLogger(__name__)

# Default debugging port for Chrome
DEFAULT_DEBUG_PORT = 9222
DEFAULT_DEBUG_HOST = "127.0.0.1"


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


def is_temp_chrome_on_port(port: int, profile_prefix: str = "nodriver_chrome_") -> tuple[bool, int | None]:
    """
    Check if the Chrome on a port is a temp profile launched by this library.

    Args:
        port: Port to check
        profile_prefix: Profile directory prefix to match (default: "nodriver_chrome_")

    Returns:
        Tuple of (is_temp_chrome, pid). If not a temp Chrome or no Chrome, returns (False, None).

    Example:
        is_ours, pid = is_temp_chrome_on_port(9222)
        if is_ours:
            print(f"Our Chrome on port 9222, PID: {pid}")
    """
    pid = get_pid_on_port(port)
    if pid is None:
        return False, None

    cmdline = get_process_cmdline(pid)
    if cmdline is None:
        return False, pid

    # Check if it's Chrome with our temp profile prefix
    if "chrome" in cmdline.lower() and profile_prefix in cmdline:
        return True, pid

    return False, pid


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


def find_temp_chromes(
    port_range: tuple[int, int] = (9222, 9300),
    profile_prefix: str = "nodriver_chrome_",
    exclude_in_use: bool = True,
) -> list[int]:
    """
    Find all ports with temp Chrome instances launched by this library.

    Scans the given port range for Chrome instances with matching profile prefix.

    Args:
        port_range: Tuple of (start_port, end_port) to scan
        profile_prefix: Profile directory prefix to match (default: "nodriver_chrome_")
        exclude_in_use: If True (default), skip ports where Chrome has attached
                       debugger sessions (detected via CDP).

    Returns:
        List of ports with matching Chrome instances.

    Example:
        ports = find_temp_chromes()
        print(f"Found {len(ports)} reusable Chrome instances")
    """
    temp_ports = []
    for port in range(port_range[0], port_range[1]):
        is_temp, _ = is_temp_chrome_on_port(port, profile_prefix)
        if is_temp:
            # Check CDP-based in-use detection
            if exclude_in_use:
                if is_chrome_in_use(port):
                    logger.debug(f"Skipping in-use Chrome on port {port} (has attached debugger)")
                    continue

            temp_ports.append(port)
    return temp_ports


def get_available_port(
    start: int = 9222,
    end: int = 9300,
    exclude: set[int] | None = None,
    profile_prefix: str = "nodriver_chrome_",
) -> int:
    """
    Find an available port for Chrome, preferring to reuse existing instances.

    Port selection strategy:
    1. First, look for existing temp Chrome (matching prefix) not in use
    2. If none found, find an unused port for launching new Chrome

    This strategy preserves login sessions and reduces startup time.

    Args:
        start: Start of port range to search (default: 9222)
        end: End of port range to search (default: 9300)
        exclude: Set of ports to skip (e.g., already assigned to workers)
        profile_prefix: Profile directory prefix to match (default: "nodriver_chrome_")

    Returns:
        An available port number

    Raises:
        RuntimeError: If no available port found in range

    Example:
        port = get_available_port(exclude={9222, 9223})
        print(f"Use port {port}")
    """
    exclude = exclude or set()

    # Strategy 1: Try to reuse existing temp Chrome not in use
    for port in range(start, end):
        if port in exclude:
            continue
        if is_port_in_use(DEFAULT_DEBUG_HOST, port):
            is_temp, _ = is_temp_chrome_on_port(port, profile_prefix)
            if is_temp and not is_chrome_in_use(port):
                logger.debug(f"Found reusable temp Chrome on port {port}")
                return port

    # Strategy 2: Find unused port for new Chrome
    for port in range(start, end):
        if port in exclude:
            continue
        if not is_port_in_use(DEFAULT_DEBUG_HOST, port):
            return port

    raise RuntimeError(f"No available port found in range {start}-{end}")
