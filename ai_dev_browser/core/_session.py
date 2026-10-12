"""Persistent lifecycle identity; never stores or replays browser input."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

from .config import DEFAULT_BASE_DIR


_DIR = DEFAULT_BASE_DIR / "sessions"


def read(session_id: str) -> dict:
    if not re.fullmatch(r"(?:cdp|extension)-[a-zA-Z0-9-]+", session_id):
        raise ValueError(
            "Invalid session_id; use the identity returned by start/connect"
        )
    try:
        return json.loads((_DIR / f"{session_id}.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise LookupError(f"Session {session_id} not found") from None


def write(record: dict) -> None:
    _write_json(_DIR / f"{record['session_id']}.json", record)


def _write_json(destination: Path, record: dict) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    # Readers must never observe half of another CLI process's JSON write.
    fd, name = tempfile.mkstemp(dir=_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream)
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)


def remember_launch(token: str, record: dict) -> None:
    """Retain observed ownership when Chrome's handshake arrives after timeout."""
    _write_json(_DIR / f"pending-{token}.json", record)


def adopt_launch(status: dict) -> dict | None:
    token = status.get("launch_token") or ""
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        return None
    path = _DIR / f"pending-{token}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not same_process(record):
        path.unlink(missing_ok=True)
        return None
    record.update(
        session_id="extension-" + status["session_id"],
        profile_id=status["profile_id"],
        automation_target_id=status.get("automation_target_id"),
        browser_version=status.get("browser_version"),
    )
    write(record)
    path.unlink(missing_ok=True)
    return record


def pending_launch(port: int) -> bool:
    """A ready worker may announce before observing its startup nonce tab."""
    for path in _DIR.glob("pending-*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if record.get("bridge_port") == port and same_process(record):
            return True
    return False


def failure(code: str, error_message: str, **state) -> dict:
    return {
        **state,
        "connected": False,
        "error": error_message,
        "error_code": code,
        "retryable": code == "transient",
    }


def process_info(pid: int | None) -> dict | None:
    """Read OS identity so a recycled PID cannot become a stop/restart target."""
    import psutil

    try:
        process = psutil.Process(pid) if pid else None
        if process is None or not process.is_running():
            return None
        return {
            "pid": pid,
            "process_created": process.create_time(),
            "chrome_path": process.exe(),
            "launch_args": process.cmdline(),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def same_process(record: dict) -> bool:
    current = process_info(record.get("pid"))
    return bool(
        current
        and current["process_created"] == record.get("process_created")
        and os.path.normcase(current["chrome_path"])
        == os.path.normcase(record.get("chrome_path", ""))
    )


def profile_processes(user_data_dir: Path) -> list[dict]:
    """Chrome locks a whole user-data-dir, including its other profile folders."""
    import psutil

    wanted = os.path.normcase(str(user_data_dir.resolve()))
    matches = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            args = process.info.get("cmdline") or []
            if any(a.startswith("--type=") for a in args):
                continue
            name = (process.info.get("name") or "").lower()
            if "chrome" not in name and "chromium" not in name:
                continue
            path = None
            for index, arg in enumerate(args):
                if arg.startswith("--user-data-dir="):
                    path = arg.split("=", 1)[1]
                elif arg == "--user-data-dir" and index + 1 < len(args):
                    path = args[index + 1]
            if path and os.path.normcase(str(Path(path).resolve())) == wanted:
                matches.append(process_info(process.pid) or {"pid": process.pid})
            elif not path:
                # A Chrome without this flag uses its platform's default data dir.
                import sys

                home = Path.home()
                defaults = (
                    [
                        Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
                        / "Google/Chrome/User Data"
                    ]
                    if sys.platform == "win32"
                    else [home / "Library/Application Support/Google/Chrome"]
                    if sys.platform == "darwin"
                    else [home / ".config/google-chrome", home / ".config/chromium"]
                )
                if wanted in {os.path.normcase(str(p.resolve())) for p in defaults}:
                    matches.append(process_info(process.pid) or {"pid": process.pid})
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return matches


def capabilities(record: dict) -> dict:
    owned = record.get("owner") == "adb"
    return {
        "can_start": True,
        "can_disconnect": True,
        "can_close": owned and bool(record.get("pid")),
        "can_restart": owned and bool(record.get("start_options")),
        "restart_requires_authorization": not owned,
        "can_select_headless_on_start": True,
        "can_change_running_headless": False,
        "profile_owned_by_caller": record.get("profile_owner") == "adb",
        "page_images": True,
        "page_input": True,
        "remote_viewer": False,
        "remote_relay": False,
    }


def describe(record: dict) -> dict:
    return {
        key: record.get(key)
        for key in (
            "session_id",
            "transport",
            "owner",
            "profile_owner",
            "pid",
            "port",
            "chrome_path",
            "user_data_dir",
            "profile_directory",
            "profile_id",
            "headless",
            "browser_version",
            "automation_target_id",
        )
    } | {"capabilities": capabilities(record)}
