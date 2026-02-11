"""Cross-platform process management utilities.

This module provides process inspection and termination:
- get_pid_on_port: Find which process is listening on a port
- get_process_cmdline: Get the command line of a process
- kill_process_tree: Terminate a process and all its children

Example:
    pid = get_pid_on_port(9350)
    if pid:
        kill_process_tree(pid)
"""

import contextlib
import logging
import platform
import subprocess


logger = logging.getLogger(__name__)


def get_pid_on_port(port: int) -> int | None:
    """
    Get the PID of the process listening on a port.

    Cross-platform: uses lsof on Unix, netstat on Windows.

    Args:
        port: Port number to check

    Returns:
        PID if found, None otherwise.

    Example:
        pid = get_pid_on_port(9350)
        if pid:
            print(f"Chrome PID: {pid}")
    """
    system = platform.system()

    if system == "Darwin" or system == "Linux":
        # Use lsof on Unix-like systems
        try:
            result = subprocess.run(
                ["lsof", "-i", f":{port}", "-t", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                # lsof -t returns just the PID
                return int(result.stdout.strip().split("\n")[0])
        except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
            pass
    elif system == "Windows":
        # Use netstat on Windows (without -p TCP to include IPv6 listeners)
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.split("\n"):
                if f":{port}" in line and "LISTENING" in line and "TCP" in line:
                    parts = line.split()
                    if parts:
                        return int(parts[-1])
        except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
            pass

    return None


def get_process_cmdline(pid: int) -> str | None:
    """
    Get the command line arguments of a process.

    Cross-platform: uses ps on Unix, PowerShell Get-CimInstance on Windows.

    Args:
        pid: Process ID

    Returns:
        Command line string if found, None otherwise.

    Example:
        cmdline = get_process_cmdline(1234)
        if cmdline and "chrome" in cmdline.lower():
            print("It's a Chrome process")
    """
    system = platform.system()

    if system == "Darwin" or system == "Linux":
        try:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "args="],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    elif system == "Windows":
        try:
            # Use PowerShell Get-CimInstance (wmic is deprecated on Windows 11)
            ps_cmd = (
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return None


def _find_chrome_processes() -> list[tuple[int, str]]:
    """Find all running Chrome processes with their command lines.

    Process-based discovery that works even when Chrome failed to bind
    its debug port (zombie Chromes). Complements port-based scanning.

    Returns:
        List of (pid, cmdline) tuples for Chrome processes.
    """
    results = []
    system = platform.system()

    try:
        if system == "Windows":
            # Use PowerShell Get-CimInstance (wmic is deprecated on Windows 11)
            ps_cmd = (
                "Get-CimInstance Win32_Process -Filter 'name=\"chrome.exe\"' "
                '| ForEach-Object { "$($_.ProcessId)`t$($_.CommandLine)" }'
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("\t", 1)
                    if len(parts) == 2:
                        try:
                            results.append((int(parts[0]), parts[1]))
                        except ValueError:
                            pass
        else:
            # Unix: ps with all processes
            result = subprocess.run(
                ["ps", "-e", "-o", "pid,args"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n")[1:]:  # Skip header
                    line = line.strip()
                    if not line or "chrome" not in line.lower():
                        continue
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        try:
                            results.append((int(parts[0]), parts[1]))
                        except ValueError:
                            pass
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        logger.debug("Failed to enumerate Chrome processes")

    return results


def _kill_process_tree(pid: int) -> bool:
    """
    Kill a process and all its children (process tree).

    On Windows, Chrome spawns child processes that continue running even after
    the parent is killed. This function kills the entire process tree.

    Cross-platform: uses taskkill /T on Windows, SIGKILL on Unix.

    Args:
        pid: Process ID to kill (including all descendants)

    Returns:
        True if kill command was executed, False on error.

    Example:
        pid = get_pid_on_port(9350)
        if pid:
            kill_process_tree(pid)
            print("Chrome terminated")
    """
    try:
        if platform.system() == "Windows":
            # Use taskkill /T to kill process tree on Windows
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        else:
            # On Unix-like systems, use SIGKILL
            import os
            import signal

            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(pid), signal.SIGKILL)  # type: ignore[attr-defined]
        return True
    except Exception as e:
        logger.warning(f"Failed to kill process tree for PID {pid}: {e}")
        return False
