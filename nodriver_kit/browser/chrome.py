"""Chrome executable detection and launching.

This module provides cross-platform Chrome management:
- find_chrome: Detect Chrome installation path
- launch_chrome: Start Chrome with remote debugging

Example:
    chrome_path = find_chrome()
    if chrome_path:
        process = launch_chrome(port=9222)
"""

import logging
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Default prefix for temp Chrome profiles
DEFAULT_PROFILE_PREFIX = "nodriver_chrome_"


def find_chrome() -> str | None:
    """
    Find Chrome executable path based on platform.

    Automatically detects Chrome installation on Windows, macOS, and Linux.
    Checks common installation paths and falls back to PATH search on Unix.

    Returns:
        Path to Chrome executable, or None if not found.

    Example:
        chrome = find_chrome()
        if chrome:
            print(f"Chrome at: {chrome}")
        else:
            print("Chrome not found")
    """
    system = platform.system()

    if system == "Darwin":  # macOS
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    elif system == "Windows":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
        ]
    else:  # Linux
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ]

    # Check known paths
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate

    # Try to find via 'which' on Unix-like systems
    if system != "Windows":
        for cmd in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]:
            result = shutil.which(cmd)
            if result:
                return result

    return None


def launch_chrome(
    port: int = 9222,
    headless: bool = False,
    user_data_dir: str | Path | None = None,
    profile_prefix: str = DEFAULT_PROFILE_PREFIX,
    extra_args: list[str] | None = None,
) -> subprocess.Popen:
    """
    Launch Chrome with remote debugging enabled.

    Creates an isolated Chrome instance with its own profile directory,
    suitable for browser automation without affecting user's Chrome.

    Args:
        port: Remote debugging port (default: 9222)
        headless: Run in headless mode (default: False)
        user_data_dir: Custom user data directory. If None, creates a temp directory.
        profile_prefix: Prefix for temp profile directory name (default: "nodriver_chrome_")
        extra_args: Additional Chrome command-line arguments

    Returns:
        Popen process handle for the Chrome instance.

    Raises:
        FileNotFoundError: If Chrome executable not found.
        RuntimeError: If Chrome fails to start.

    Example:
        process = launch_chrome(port=9222)
        # ... connect with nodriver ...
        process.terminate()
    """
    chrome_path = find_chrome()
    if not chrome_path:
        raise FileNotFoundError(
            "Chrome executable not found. Please install Google Chrome or set the path manually."
        )

    # Create isolated user data directory if not provided
    if user_data_dir is None:
        user_data_dir = tempfile.mkdtemp(prefix=profile_prefix)

    # Build Chrome arguments (cross-platform)
    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--remote-allow-origins=*",  # Allow CDP connections for in-use detection
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-client-side-phishing-detection",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-hang-monitor",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        "--disable-sync",
        "--disable-translate",
        "--metrics-recording-only",
        "--safebrowsing-disable-auto-update",
    ]

    if headless:
        args.append("--headless=new")

    if extra_args:
        args.extend(extra_args)

    # Start Chrome process
    try:
        # Use subprocess.Popen on all platforms
        # On Unix, use start_new_session to detach from parent
        # On Windows, CREATE_NEW_PROCESS_GROUP for similar isolation
        if platform.system() == "Windows":
            popen_kwargs = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.PIPE,
                "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
            }
        else:
            popen_kwargs = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.PIPE,
                "start_new_session": True,
            }

        logger.debug(f"Launching Chrome on port {port}")
        process = subprocess.Popen(args, **popen_kwargs)

        logger.debug(f"Chrome process created, PID: {process.pid}")
    except Exception as e:
        raise RuntimeError(f"Failed to launch Chrome: {e}") from e

    return process
