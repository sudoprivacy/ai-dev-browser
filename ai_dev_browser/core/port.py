"""Port management for Chrome debugging.

This module provides port scanning and availability detection:
- is_port_in_use: Check if a port is occupied
- get_available_port: Find an available debugging port
- find_debug_chromes: Find all debugging Chrome instances

Example:
    port = get_available_port()
    print(f"Available port: {port}")
"""

import logging
import shutil
import socket
import tempfile
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
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
            return True
    except OSError:
        return False


def is_port_in_use(
    host: str = DEFAULT_DEBUG_HOST,
    port: int = DEFAULT_DEBUG_PORT,
    timeout: float = 0.1,
) -> bool:
    """Check if a port is in use (Chrome might be listening).

    Uses a bind-first strategy for speed on Windows.

    Args:
        host: Host to check (default: 127.0.0.1)
        port: Port to check (default: DEFAULT_DEBUG_PORT)
        timeout: Connection timeout in seconds

    Returns:
        True if port is in use, False otherwise.
    """
    # Fast path: if we can bind, nothing is listening (sub-millisecond)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
        return False
    except OSError:
        pass

    # Check IPv4
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect((host, port))
            return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        pass

    # Check IPv6
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            ipv6_host = "::1" if host in ("127.0.0.1", "localhost") else host
            sock.connect((ipv6_host, port))
            return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        pass

    return False


def get_available_port(
    start: int = None,
    end: int = None,
    exclude: set[int] | None = None,
    reuse: bool = True,
) -> int:
    """Find an available port for Chrome.

    Args:
        start: Start of port range
        end: End of port range
        exclude: Ports to skip
        reuse: If True, prefer reusing existing Chrome instances.
               TODO: will be filtered by workspace once ownership is implemented.

    Returns:
        An available port number

    Raises:
        RuntimeError: If no available port found in range
    """
    if start is None:
        start = DEFAULT_PORT_RANGE[0]
    if end is None:
        end = DEFAULT_PORT_RANGE[1]
    port_range = (start, end)

    if reuse:
        # TODO: filter by workspace (pwd) once ownership is implemented
        exclude = exclude or set()
        for chrome_port, _pid in find_debug_chromes(port_range):
            if chrome_port in exclude:
                continue
            # For now, reuse any debugging Chrome found
            return chrome_port

    # Find unused port
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
    """Find all Chrome instances with --remote-debugging-port.

    Uses process enumeration instead of port scanning.

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
    """Clean up temp profile directory for a port if it exists."""
    temp_dir = Path(tempfile.gettempdir()) / f"{profile_prefix}{port}"
    if temp_dir.exists():
        try:
            shutil.rmtree(temp_dir)
            logger.debug(f"Cleaned up temp profile: {temp_dir}")
            return True
        except Exception as e:
            logger.warning(f"Failed to clean up temp profile {temp_dir}: {e}")
    return False
