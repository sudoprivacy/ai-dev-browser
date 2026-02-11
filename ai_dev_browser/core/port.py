"""Port management for Chrome debugging.

This module provides port scanning and availability detection:
- is_port_in_use: Check if a port is occupied
- get_available_port: Find an available debugging port
- find_debug_chromes: Find all debugging Chrome instances
- is_chrome_in_use: Check if a Chrome is being used via CDP

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

from .config import (
    DEFAULT_DEBUG_HOST,
    DEFAULT_DEBUG_PORT,
    DEFAULT_PORT_RANGE,
    DEFAULT_PROFILE_PREFIX,
)
from .process import _find_chrome_processes, get_pid_on_port, get_process_cmdline


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


def _is_port_bindable(
    host: str = DEFAULT_DEBUG_HOST, port: int = DEFAULT_DEBUG_PORT
) -> bool:
    """Check if a port can actually be bound (not reserved by the OS).

    On Windows, Hyper-V reserves dynamic port ranges that appear "unused"
    (nothing is listening) but reject bind() with WSAEACCES (0x271D).
    This function catches that by attempting an actual bind.

    Args:
        host: Host to bind on
        port: Port to test

    Returns:
        True if the port is bindable, False if the OS rejects it.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
            return True
    except OSError:
        return False


def is_port_in_use(
    host: str = DEFAULT_DEBUG_HOST, port: int = DEFAULT_DEBUG_PORT, timeout: float = 0.1
) -> bool:
    """
    Check if a port is in use (Chrome might be listening).

    Uses a bind-first strategy for speed on Windows: if we can bind the port,
    nothing is listening — skip the slow connect(). On Windows 11 with Hyper-V,
    connect() to unused ports hangs until timeout (100ms each) instead of
    giving an instant ConnectionRefused, making naive scanning 20s+ for 100 ports.

    Args:
        host: Host to check (default: 127.0.0.1)
        port: Port to check (default: DEFAULT_DEBUG_PORT)
        timeout: Connection timeout in seconds (default 0.1s for fast scanning)

    Returns:
        True if port is in use, False otherwise.

    Example:
        if is_port_in_use(port=9350):
            print("Chrome already running on 9350")
    """
    # Fast path: if we can bind, nothing is listening (sub-millisecond)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
        return False
    except OSError:
        pass
    # Bind failed: either something is listening, or Hyper-V reserved.
    # Use connect to distinguish (only reached for non-bindable ports).

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
        if is_chrome_in_use(9350):
            print("Chrome on 9350 is busy, find another port")
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
    start: int = None,
    end: int = None,
    exclude: set[int] | None = None,
    reuse: bool = True,
) -> int:
    """
    Find an available port for Chrome.

    Port selection strategy (when reuse=True):
    1. First, look for any idle debugging Chrome (not in use via CDP)
    2. If none found, find an unused port for launching new Chrome

    When reuse=False, skips directly to finding an unused port.

    Args:
        start: Start of port range to search (default: from DEFAULT_PORT_RANGE)
        end: End of port range to search (default: from DEFAULT_PORT_RANGE)
        exclude: Set of ports to skip (e.g., already assigned to workers)
        reuse: If True (default), prefer reusing existing Chrome instances.
               If False, only find unused ports for new Chrome.

    Returns:
        An available port number

    Raises:
        RuntimeError: If no available port found in range

    Example:
        port = get_available_port(exclude={9350, 9351})
        port = get_available_port(reuse=False)  # Always get fresh port
    """
    # Use defaults from config if not specified
    if start is None:
        start = DEFAULT_PORT_RANGE[0]
    if end is None:
        end = DEFAULT_PORT_RANGE[1]
    port_range = (start, end)

    if reuse:
        # Reuse any idle debugging Chrome (process-based, no port scanning)
        exclude = exclude or set()
        for chrome_port, _pid in find_debug_chromes(port_range):
            if chrome_port in exclude:
                continue
            if not is_chrome_in_use(chrome_port):
                logger.debug(f"Found reusable idle Chrome on port {chrome_port}")
                return chrome_port

    # Find unused port (or only strategy when reuse=False)
    # Use bind-only test: bindable = nothing listening AND not Hyper-V reserved.
    # This avoids slow connect() calls on Windows with Hyper-V.
    for p in range(port_range[0], port_range[1]):
        if exclude and p in exclude:
            continue
        if _is_port_bindable(DEFAULT_DEBUG_HOST, p):
            return p

    raise RuntimeError(
        f"No available port found in range {port_range[0]}-{port_range[1]}"
    )


def find_debug_chromes(
    port_range: tuple[int, int] = DEFAULT_PORT_RANGE,
) -> list[tuple[int, int]]:
    """
    Find all Chrome instances with --remote-debugging-port.

    Uses process enumeration instead of port scanning — immune to Hyper-V
    reserved ports on Windows (which make port scanning 20s+ slow).

    Args:
        port_range: Tuple of (start_port, end_port) to filter results

    Returns:
        List of (port, pid) tuples for each found Chrome
    """
    import re

    chromes = []
    for pid, cmdline in _find_chrome_processes():
        # Skip child processes (renderers, GPU, etc.)
        if "--type=" in cmdline:
            continue
        # Extract --remote-debugging-port=XXXX
        match = re.search(r"--remote-debugging-port=(\d+)", cmdline)
        if not match:
            continue
        port = int(match.group(1))
        if port_range[0] <= port < port_range[1]:
            chromes.append((port, pid))

    return chromes


def _cleanup_temp_profile(
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
