"""Chrome executable detection and launching.

This module provides cross-platform Chrome management:
- find_chrome: Detect Chrome installation path
- launch_chrome: Start Chrome with remote debugging

Example:
    chrome_path = find_chrome()
    if chrome_path:
        process = launch_chrome()
"""

import logging
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import DEFAULT_DEBUG_PORT, DEFAULT_PROFILE_PREFIX


logger = logging.getLogger(__name__)


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
            str(
                Path.home()
                / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            ),
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
        for cmd in [
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
        ]:
            result = shutil.which(cmd)
            if result:
                return result

    return None


def _ensure_no_session_restore(user_data_dir: Path) -> None:
    """Ensure Chrome won't restore previous session on startup.

    Sets restore_on_startup=5 in Preferences file, which tells Chrome
    to open a new tab page instead of restoring previous tabs.

    Args:
        user_data_dir: Chrome user data directory path
    """
    import json

    default_dir = user_data_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)

    prefs_file = default_dir / "Preferences"

    # Load existing preferences or start fresh
    prefs = {}
    if prefs_file.exists():
        try:
            prefs = json.loads(prefs_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prefs = {}

    # Set restore_on_startup to 5 (open new tab page)
    if "session" not in prefs:
        prefs["session"] = {}
    prefs["session"]["restore_on_startup"] = 5

    # Write back
    try:
        prefs_file.write_text(json.dumps(prefs), encoding="utf-8")
        logger.debug(f"Set restore_on_startup=5 in {prefs_file}")
    except OSError as e:
        logger.warning(f"Failed to write Preferences: {e}")


def launch_chrome(
    port: int = DEFAULT_DEBUG_PORT,
    headless: bool = False,
    user_data_dir: str | Path | None = None,
    profile_prefix: str = DEFAULT_PROFILE_PREFIX,
    extra_args: list[str] | None = None,
    start_url: str = "about:blank",
    disable_session_restore: bool = True,
    disable_session_crashed_bubble: bool = True,
    hide_crash_restore_bubble: bool = True,
) -> subprocess.Popen:
    """
    Launch Chrome with remote debugging enabled.

    Creates an isolated Chrome instance with its own profile directory,
    suitable for browser automation without affecting user's Chrome.

    Args:
        port: Remote debugging port (default: DEFAULT_DEBUG_PORT)
        headless: Run in headless mode (default: False)
        user_data_dir: Custom user data directory. If None, creates a temp directory.
        profile_prefix: Prefix for temp profile directory name
        extra_args: Additional Chrome command-line arguments
        start_url: Initial URL to open (default: "about:blank" for clean state)
        disable_session_restore: Prevent Chrome from restoring previous tabs (default: True).
                                Sets restore_on_startup=5 in Preferences file.
        disable_session_crashed_bubble: Chrome flag --disable-session-crashed-bubble (default: True)
        hide_crash_restore_bubble: Chrome flag --hide-crash-restore-bubble (default: True)

    Returns:
        Popen process handle for the Chrome instance.

    Raises:
        FileNotFoundError: If Chrome executable not found.
        RuntimeError: If Chrome fails to start.

    Example:
        process = launch_chrome()
        # ... connect via CDP ...
        process.terminate()
    """
    chrome_path = find_chrome()
    if not chrome_path:
        raise FileNotFoundError(
            "Chrome executable not found. Please install Google Chrome or set the path manually."
        )

    # Create isolated user data directory if not provided
    # Use port number in name so browser_stop can find and clean it up
    if user_data_dir is None:
        temp_dir = Path(tempfile.gettempdir()) / f"{profile_prefix}{port}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        user_data_dir = str(temp_dir)

    # Disable session restore by setting Preferences
    # This prevents Chrome from restoring previous tabs on startup
    if disable_session_restore:
        _ensure_no_session_restore(Path(user_data_dir))

    # Build Chrome arguments (cross-platform)
    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--remote-allow-origins=*",  # Allow CDP connections for in-use detection
        "--enable-automation",  # Required for CDP Browser.getBrowserCommandLine()
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

    # Workspace tag: identifies which working directory owns this Chrome.
    # Read back via CDP Browser.getBrowserCommandLine() in port.py.
    args.append(f"--ai-dev-browser-workspace={os.getcwd()}")

    # Session restore behavior (default: suppress for clean automation state)
    if disable_session_crashed_bubble:
        args.append("--disable-session-crashed-bubble")
    if hide_crash_restore_bubble:
        args.append("--hide-crash-restore-bubble")

    if headless:
        args.append("--headless=new")

    if extra_args:
        args.extend(extra_args)

    # Start URL goes last - use start_url parameter to control initial page
    if start_url:
        args.append(start_url)

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
        process = subprocess.Popen(args, **popen_kwargs)  # type: ignore[call-overload]

        logger.debug(f"Chrome process created, PID: {process.pid}")
    except Exception as e:
        raise RuntimeError(f"Failed to launch Chrome: {e}") from e

    return process
