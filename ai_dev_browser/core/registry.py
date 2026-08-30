"""Registry of ai-dev-browser-launched Chrome instances (port → workspace/profile).

Why this exists: workspace and profile discovery used to read Chrome's command
line over CDP (`Browser.getBrowserCommandLine`), which only returns anything when
Chrome runs with `--enable-automation` — a bot-detection signal we drop by
default (stealth, see `chrome.launch_chrome`). This registry is the
automation-flag-free replacement.

Each launched Chrome writes a small record ``{port, guid, pid, workspace,
user_data_dir}``. A live debug port is matched back to its record by the browser
GUID from ``/json/version`` (unique per browser process, so a reused port can't
alias a stale record). No CDP automation flag, no process enumeration, no psutil.

Best-effort by design: a missing/failed record only degrades discovery to the
`getBrowserCommandLine` fallback (which still works for `stealth=False` Chromes)
— it must never fail a launch or a stop.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import DEFAULT_BASE_DIR

logger = logging.getLogger(__name__)

# One file per port keeps writes atomic-per-instance (parallel workers never
# contend on a shared file) and makes stop-time cleanup a single unlink.
_REGISTRY_DIR = DEFAULT_BASE_DIR / "instances"


def _entry_path(port: int) -> Path:
    return _REGISTRY_DIR / f"{port}.json"


def register_instance(
    port: int,
    guid: str | None,
    workspace: str | None,
    pid: int | None,
    user_data_dir: str | None = None,
) -> None:
    """Record a launched Chrome. Best-effort — a write failure degrades
    discovery to the cmdline fallback, it must never fail the launch."""
    try:
        _REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        _entry_path(port).write_text(
            json.dumps(
                {
                    "port": port,
                    "guid": guid,
                    "pid": pid,
                    "workspace": workspace,
                    "user_data_dir": user_data_dir,
                }
            ),
            encoding="utf-8",
        )
    except OSError as e:
        logger.debug("instance registry write failed (port %s): %s", port, e)


def lookup(port: int, guid: str | None) -> dict | None:
    """Return the record for ``port`` iff its stored guid matches the live
    ``guid`` — guards against a different Chrome having taken a reused port.

    A guid-mismatched file is pruned opportunistically (the browser that wrote
    it is gone; a new one now owns the port)."""
    try:
        entry = json.loads(_entry_path(port).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if guid and entry.get("guid") == guid:
        return entry
    if guid and entry.get("guid") != guid:
        unregister_instance(port)
    return None


def unregister_instance(port: int) -> None:
    """Delete a port's record (on browser_stop, or when found stale)."""
    try:
        _entry_path(port).unlink()
    except OSError:
        pass


def registered_ports() -> set[int]:
    """Ports adb has launched a Chrome on (one record file each).

    The deterministic "these are mine" set: a blanket stop scopes to this so it
    can never reap a debug Chrome adb didn't launch. Best-effort — a missing dir
    just yields an empty set."""
    ports: set[int] = set()
    try:
        for entry in _REGISTRY_DIR.glob("*.json"):
            try:
                ports.add(int(entry.stem))
            except ValueError:
                continue
    except OSError:
        pass
    return ports
