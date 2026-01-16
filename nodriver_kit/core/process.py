"""Cross-platform process management utilities.

This module provides process inspection and termination:
- get_pid_on_port: Find which process is listening on a port
- get_process_cmdline: Get the command line of a process
- kill_process_tree: Terminate a process and all its children

Example:
    pid = get_pid_on_port(9222)
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
        pid = get_pid_on_port(9222)
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

    Cross-platform: uses ps on Unix, wmic on Windows.

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
            result = subprocess.run(
                ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                lines = [line.strip() for line in result.stdout.split("\n") if line.strip()]
                if len(lines) > 1:
                    return lines[1]  # Skip header
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return None


def kill_process_tree(pid: int) -> bool:
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
        pid = get_pid_on_port(9222)
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
                os.killpg(os.getpgid(pid), signal.SIGKILL)
        return True
    except Exception as e:
        logger.warning(f"Failed to kill process tree for PID {pid}: {e}")
        return False
