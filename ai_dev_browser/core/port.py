"""Port management for Chrome debugging.

Discovery uses port scanning + CDP (no process enumeration):
  1. Scan port range for listening ports (socket.connect)
  2. Hit /json/version to confirm Chrome debug port
  3. CDP Browser.getBrowserCommandLine() to read workspace tag

Example:
    port = get_available_port()
    chromes = find_debug_chromes()
"""

import json
import logging
import os
import shutil
import socket
import tempfile
import urllib.request
from pathlib import Path

from .config import (
    DEFAULT_DEBUG_HOST,
    DEFAULT_PORT_RANGE,
    DEFAULT_PROFILE_PREFIX,
)
from .process import get_pid_on_port


logger = logging.getLogger(__name__)


# =============================================================================
# CDP-based Chrome Discovery
# =============================================================================


def _query_chrome_cmdline(
    port: int,
    host: str = DEFAULT_DEBUG_HOST,
    timeout: float = 2.0,
) -> list[str] | None:
    """Query Chrome's command line via CDP Browser.getBrowserCommandLine.

    Two-step: HTTP /json/version to get WebSocket URL, then sync
    WebSocket CDP call to get command line arguments.

    Args:
        port: Chrome debug port to query.
        host: Host address.
        timeout: Timeout for HTTP and WebSocket operations.

    Returns:
        List of command line arguments, or None if not a Chrome debug port.
    """
    try:
        # Step 1: HTTP — confirm Chrome debug port, get WebSocket URL
        resp = urllib.request.urlopen(
            f"http://{host}:{port}/json/version", timeout=timeout
        )
        info = json.loads(resp.read())
        ws_url = info.get("webSocketDebuggerUrl")
        if not ws_url:
            return None

        # Step 2: Sync WebSocket — CDP Browser.getBrowserCommandLine
        import websocket  # websocket-client (sync)

        ws = websocket.create_connection(ws_url, timeout=timeout)
        try:
            ws.send(json.dumps({"id": 1, "method": "Browser.getBrowserCommandLine"}))
            result = json.loads(ws.recv())
            return result.get("result", {}).get("arguments", [])
        finally:
            ws.close()
    except Exception:
        return None


def _extract_workspace(cmdline: list[str]) -> str | None:
    """Extract --ai-dev-browser-workspace= value from command line args."""
    for arg in cmdline:
        if arg.startswith("--ai-dev-browser-workspace="):
            return arg.split("=", 1)[1].strip().strip('"').strip("'")
    return None


# =============================================================================
# Port Detection
# =============================================================================


def _is_port_bindable(host: str = DEFAULT_DEBUG_HOST, port: int = 9350) -> bool:
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
    port: int = 9350,
    timeout: float = 0.1,
) -> bool:
    """Check if a port is in use (Chrome might be listening).

    Uses a bind-first strategy for speed on Windows.

    Args:
        host: Host to check (default: 127.0.0.1)
        port: Port to check
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
        reuse: If True, prefer reusing existing Chrome instances in the current workspace.

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
        exclude = exclude or set()
        # Prefer Chromes in the current workspace
        for chrome_port, _pid in find_workspace_chromes(port_range=port_range):
            if chrome_port not in exclude:
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


# =============================================================================
# Chrome Instance Discovery (port scan + CDP)
# =============================================================================


def find_debug_chromes(
    port_range: tuple[int, int] = DEFAULT_PORT_RANGE,
) -> list[tuple[int, int | None, str | None]]:
    """Find all Chrome instances with remote debugging enabled.

    Scans port range and uses CDP to identify Chrome instances and
    extract their workspace tags. No process enumeration needed.

    Args:
        port_range: Tuple of (start_port, end_port) to scan

    Returns:
        List of (port, pid, workspace) tuples for each found Chrome.
        workspace is the --ai-dev-browser-workspace value, or None if absent.
    """
    chromes = []
    for port in range(port_range[0], port_range[1]):
        if not is_port_in_use(port=port):
            continue
        cmdline = _query_chrome_cmdline(port)
        if cmdline is None:
            continue
        workspace = _extract_workspace(cmdline)
        pid = get_pid_on_port(port)
        chromes.append((port, pid, workspace))

    return chromes


def find_workspace_chromes(
    workspace: str | None = None,
    port_range: tuple[int, int] = DEFAULT_PORT_RANGE,
) -> list[tuple[int, int | None]]:
    """Find debug Chromes belonging to the given workspace.

    Args:
        workspace: Working directory to match. Defaults to os.getcwd().
        port_range: Tuple of (start_port, end_port) to scan

    Returns:
        List of (port, pid) tuples for Chromes matching the workspace.
    """
    if workspace is None:
        workspace = os.getcwd()
    workspace = os.path.normcase(os.path.normpath(workspace))

    results = []
    for port, pid, ws in find_debug_chromes(port_range):
        if ws is not None and os.path.normcase(os.path.normpath(ws)) == workspace:
            results.append((port, pid))
    return results


# =============================================================================
# Temp Profile Cleanup
# =============================================================================


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
