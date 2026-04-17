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
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor

from .config import (
    DEFAULT_DEBUG_HOST,
    DEFAULT_EPHEMERAL_RANGE,
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


def _allocate_ephemeral_port(
    host: str = DEFAULT_DEBUG_HOST, exclude: set[int] | None = None
) -> int:
    """Ask the OS for an ephemeral port via bind(0).

    The OS never hands out reserved ports, so this works even when the
    preferred range is fully blocked (e.g. Windows Hyper-V).
    """
    exclude = exclude or set()
    # Retry a few times in case OS hands us an excluded port (very unlikely)
    for _ in range(10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            port = sock.getsockname()[1]
        if port not in exclude:
            return port
    raise RuntimeError("Could not obtain an ephemeral port not in exclude set")


def get_available_port(
    start: int = None,
    end: int = None,
    exclude: set[int] | None = None,
    reuse: bool = True,
) -> int:
    """Find an available port for Chrome.

    Tries the preferred range first (so ports stay in a scannable band).
    If the range is fully unbindable — typically Windows Hyper-V reserving
    the whole chunk at boot — falls back to an OS-assigned ephemeral port.
    Two-tier discovery in find_debug_chromes() covers both cases.

    Args:
        start: Start of port range
        end: End of port range
        exclude: Ports to skip
        reuse: If True, prefer reusing existing Chrome instances in the current workspace.

    Returns:
        An available port number.
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

    # Find unused port in preferred range
    for p in range(port_range[0], port_range[1]):
        if exclude and p in exclude:
            continue
        if _is_port_bindable(DEFAULT_DEBUG_HOST, p):
            return p

    # Preferred range fully unbindable — fall back to OS ephemeral port.
    # Discovery widens to DEFAULT_EPHEMERAL_RANGE so this Chrome stays findable.
    fallback = _allocate_ephemeral_port(DEFAULT_DEBUG_HOST, exclude)
    logger.warning(
        "Port range %d-%d fully unbindable (likely Windows Hyper-V reserved); "
        "falling back to OS-assigned port %d. Discovery will scan the OS "
        "ephemeral range to find it.",
        port_range[0],
        port_range[1],
        fallback,
    )
    return fallback


# =============================================================================
# Chrome Instance Discovery (port scan + CDP)
# =============================================================================


_os_ephemeral_range_cache: tuple[int, int] | None = None


def _get_os_ephemeral_range() -> tuple[int, int]:
    """Query the OS for its dynamic / ephemeral port range.

    Narrows the slow-path scan to exactly the band bind(0) allocates from
    — much faster than scanning the full IANA 1024-65535 superset.

    Cached after first call.

    Fallback: DEFAULT_EPHEMERAL_RANGE if query fails.
    """
    global _os_ephemeral_range_cache
    if _os_ephemeral_range_cache is not None:
        return _os_ephemeral_range_cache

    system = platform.system()
    try:
        if system == "Windows":
            # netsh int ipv4 show dynamicport tcp
            result = subprocess.run(
                ["netsh", "int", "ipv4", "show", "dynamicport", "tcp"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            start_m = re.search(r"Start Port\s*:\s*(\d+)", result.stdout)
            num_m = re.search(r"Number of Ports\s*:\s*(\d+)", result.stdout)
            if start_m and num_m:
                start = int(start_m.group(1))
                num = int(num_m.group(1))
                _os_ephemeral_range_cache = (start, start + num)
                return _os_ephemeral_range_cache
        elif system == "Linux":
            with open("/proc/sys/net/ipv4/ip_local_port_range") as f:
                parts = f.read().split()
                _os_ephemeral_range_cache = (int(parts[0]), int(parts[1]) + 1)
                return _os_ephemeral_range_cache
        elif system == "Darwin":
            first = subprocess.run(
                ["sysctl", "-n", "net.inet.ip.portrange.first"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            last = subprocess.run(
                ["sysctl", "-n", "net.inet.ip.portrange.last"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            _os_ephemeral_range_cache = (
                int(first.stdout.strip()),
                int(last.stdout.strip()) + 1,
            )
            return _os_ephemeral_range_cache
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        pass

    _os_ephemeral_range_cache = DEFAULT_EPHEMERAL_RANGE
    return _os_ephemeral_range_cache


def _fast_listening_check(
    port: int, host: str = DEFAULT_DEBUG_HOST, timeout: float = 0.005
) -> bool:
    """Listening-port probe tuned for bulk scanning.

    Skips the IPv6 fallback and uses a tight timeout. Works because:
      - localhost listeners accept in microseconds, 20ms is ample
      - Chrome debug ports always bind IPv4

    Trades completeness (IPv6-only services invisible) for speed —
    the scan completes in ~1-2s instead of ~7s on Hyper-V machines.
    """
    # Fast path: bind succeeds → nothing is listening
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
        return False
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect((host, port))
        return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        return False


def _scan_ports_for_chrome(
    port_range: tuple[int, int],
    listening_workers: int = 256,
    cdp_workers: int = 16,
    cdp_timeout: float = 0.5,
) -> list[tuple[int, int | None, str | None]]:
    """Scan a port range for Chrome debug instances (parallelized).

    Two stages:
      1. Parallel _fast_listening_check() — filter down to listening ports
         (bind-first + tight-timeout IPv4 connect, no IPv6)
      2. Parallel _query_chrome_cmdline() — verify each is Chrome and
         extract workspace tag

    Wide worker counts and short timeouts keep scans of the full OS
    ephemeral range (~14-16k ports) under 2s.
    """
    ports = list(range(port_range[0], port_range[1]))

    with ThreadPoolExecutor(max_workers=listening_workers) as pool:
        listening = [
            p
            for p, live in pool.map(lambda p: (p, _fast_listening_check(p)), ports)
            if live
        ]

    if not listening:
        return []

    def _probe(p: int) -> tuple[int, list[str] | None]:
        return p, _query_chrome_cmdline(p, timeout=cdp_timeout)

    chromes = []
    with ThreadPoolExecutor(max_workers=cdp_workers) as pool:
        for p, cmdline in pool.map(_probe, listening):
            if cmdline is None:
                continue
            workspace = _extract_workspace(cmdline)
            pid = get_pid_on_port(p)
            chromes.append((p, pid, workspace))

    return chromes


def find_debug_chromes(
    port_range: tuple[int, int] = DEFAULT_PORT_RANGE,
) -> list[tuple[int, int | None, str | None]]:
    """Find all Chrome instances with remote debugging enabled.

    Two-tier scan:
      1. Fast path: the preferred range (DEFAULT_PORT_RANGE by default, ~100 ports)
      2. Slow path: the OS ephemeral range (DEFAULT_EPHEMERAL_RANGE, ~16k ports),
         only triggered when the fast path finds nothing AND the caller didn't
         pass a custom port_range

    Tier 2 catches Chromes that get_available_port() allocated via bind(0)
    fallback when the preferred range was Hyper-V reserved.

    Args:
        port_range: Tuple of (start_port, end_port). Pass a custom range to
            restrict the scan to just that range (disables the slow-path tier).

    Returns:
        List of (port, pid, workspace) tuples for each found Chrome.
        workspace is the --ai-dev-browser-workspace value, or None if absent.
    """
    chromes = _scan_ports_for_chrome(port_range)
    if chromes:
        return chromes

    # Slow path only when (a) caller didn't pin a custom range, and (b) the
    # preferred range is fully unbindable — the Hyper-V fingerprint that
    # forces get_available_port() into bind(0) fallback. Without the (b)
    # guard every "no Chrome running" call would pay the ephemeral-range
    # scan for nothing.
    if port_range == DEFAULT_PORT_RANGE and _range_fully_unbindable(port_range):
        return _scan_ports_for_chrome(_get_os_ephemeral_range())

    return chromes


def _range_fully_unbindable(port_range: tuple[int, int]) -> bool:
    """True if every port in the range rejects bind() (Hyper-V full-reserve)."""
    for p in range(port_range[0], port_range[1]):
        if _is_port_bindable(DEFAULT_DEBUG_HOST, p):
            return False
    return True


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
