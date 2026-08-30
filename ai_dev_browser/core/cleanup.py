"""Chrome inventory + orphan cleanup for ai-dev-browser-managed profiles.

Two jobs, one determinism source:

- **Inventory** (`list_chromes`, read-only): enumerate every running Chrome
  MAIN process and classify each by `origin` — `adb` (a live debug Chrome adb
  launched), `adb-orphan` (an adb-managed Chrome with no live debug owner — a
  leftover holding a profile lock), or `external` (the user's own Chrome, whose
  `--user-data-dir` is outside adb's namespace). This is how a caller tells
  "mine" from "yours" deterministically instead of guessing from window titles.

- **Cleanup** (`browser_cleanup`): kill orphan process trees so the next
  `browser_start` isn't blocked by a stale profile lock. Safe by construction —
  it only ever targets `adb-orphan` processes within adb's managed namespace, so
  it can NEVER touch the user's real Chrome. The kill scope is REQUIRED (no
  blanket default), with `dry_run` to preview.

`psutil` is the only reliable cross-platform way to read every chrome.exe's
command line; it's an optional extra so users who never need this don't pay the
install cost.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

from .config import (
    DEFAULT_PROFILE_DIR,
    DEFAULT_PROFILE_PREFIX,
    get_workspace_profile_dir,
    get_workspace_slug,
)
from .port import _query_chrome_user_data_dir, find_debug_chromes
from .process import _kill_process_tree


logger = logging.getLogger(__name__)

_PSUTIL_HINT = (
    "This needs psutil (the cross-platform way to read every Chrome's command "
    "line). Install via: pip install 'ai-dev-browser[cleanup]'. After install, "
    "retry."
)


def _require_psutil():
    try:
        import psutil

        return psutil
    except ImportError as e:
        raise ImportError(_PSUTIL_HINT) from e


def _normalize_path(path: str) -> str:
    """Normalize a path for comparison (resolves separators + Windows case)."""
    return os.path.normcase(os.path.normpath(path))


def _is_managed_profile(user_data_dir_normalized: str) -> bool:
    """True iff the user_data_dir is inside our managed namespace.

    Two namespaces:
      - Workspace profiles: under `DEFAULT_PROFILE_DIR`
        (`~/.ai-dev-browser/profiles/...`)
      - Temp profiles: directory name starts with `DEFAULT_PROFILE_PREFIX`
        (`ai_dev_browser_<port>` in the system temp dir)
    """
    workspace_root = _normalize_path(str(DEFAULT_PROFILE_DIR))
    if user_data_dir_normalized.startswith(workspace_root):
        return True
    name = Path(user_data_dir_normalized).name
    return name.startswith(DEFAULT_PROFILE_PREFIX)


def _workspace_slug_of(udd_normalized: str | None) -> str | None:
    """Workspace slug for a managed WORKSPACE profile, else None.

    `~/.ai-dev-browser/profiles/<slug>/<profile>` → `<slug>`. Temp profiles
    (`ai_dev_browser_*`) and external Chromes aren't workspace-scoped → None.
    """
    if not udd_normalized:
        return None
    root = _normalize_path(str(DEFAULT_PROFILE_DIR))
    if udd_normalized.startswith(root):
        rest = udd_normalized[len(root) :].strip("\\/")
        return rest.split(os.sep)[0] if rest else None
    return None


def _arg_value(cmdline: list[str], flag: str) -> str | None:
    """Value of a `--flag=value` Chrome command-line argument, or None."""
    prefix = flag + "="
    for arg in cmdline:
        if arg.startswith(prefix):
            return arg.split("=", 1)[1]
    return None


def _iter_chrome_main_processes(psutil):
    """Yield (proc, cmdline) for Chrome MAIN browser processes only.

    Renderer / GPU / utility children carry a `--type=` flag; the main browser
    process does not. Skipping `--type=` isolates one entry per Chrome instance.
    """
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if "chrome" not in name and "chromium" not in name:
                continue
            cmdline = proc.info.get("cmdline") or []
            if any(a.startswith("--type=") for a in cmdline):
                continue
            yield proc, cmdline
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def list_chromes(all_workspaces: bool = True) -> list[dict]:
    """Every running Chrome MAIN process, classified by origin. Read-only.

    Each entry: `{pid, port, origin, user_data_dir, profile, workspace}` where
    `port` is the debug port (None if none), `origin` is adb / adb-orphan /
    external, and `workspace` is the slug for managed workspace profiles (None
    for temp / external).

    `all_workspaces=False` filters adb/adb-orphan entries to the current
    workspace (external Chromes are always shown — they aren't workspace-scoped).

    Requires psutil (the `cleanup` extra).
    """
    psutil = _require_psutil()

    # Live debug owners: normalized user-data-dir of every Chrome answering a
    # debug port. Managed-and-live → adb; managed-and-not-live → adb-orphan.
    alive_dirs: set[str] = set()
    for port, _pid, _ws in find_debug_chromes():
        udd = _query_chrome_user_data_dir(port)
        if udd:
            alive_dirs.add(_normalize_path(udd))

    current_slug = get_workspace_slug()
    chromes: list[dict] = []
    for proc, cmdline in _iter_chrome_main_processes(psutil):
        try:
            pid = proc.info["pid"]
        except Exception:
            continue
        udd = _arg_value(cmdline, "--user-data-dir")
        udd_norm = _normalize_path(udd) if udd else None
        debug_port = _arg_value(cmdline, "--remote-debugging-port")
        profile_dir = _arg_value(cmdline, "--profile-directory") or "Default"
        managed = bool(udd_norm and _is_managed_profile(udd_norm))

        if not managed:
            origin = "external"
        elif udd_norm in alive_dirs:
            origin = "adb"
        else:
            origin = "adb-orphan"

        workspace = _workspace_slug_of(udd_norm)
        if not all_workspaces and origin != "external":
            # Hide OTHER workspaces' adb Chromes by default; keep this workspace's
            # and any un-attributable (temp) ones so orphans stay visible.
            if workspace is not None and workspace != current_slug:
                continue

        chromes.append(
            {
                "pid": pid,
                "port": int(debug_port) if debug_port else None,
                "origin": origin,
                "user_data_dir": udd,
                "profile": profile_dir,
                "workspace": workspace,
            }
        )

    order = {"adb": 0, "adb-orphan": 1, "external": 2}
    chromes.sort(key=lambda c: (order.get(c["origin"], 3), c["pid"]))
    return chromes


def browser_cleanup(
    scope: Literal["temp", "profile", "workspace"],
    profile: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Use when: long sessions left orphan chrome.exe processes holding managed
    profile-dir locks, so a fresh `browser_start` fails ("started but port not
    listening"). Reaps ONLY adb's own orphans — never your real Chrome — and the
    kill `scope` is REQUIRED so a blanket sweep can't happen by accident. Pair
    with `browser_list` to see what's an `adb-orphan` before reaping; `dry_run`
    previews the exact PIDs without killing.

    Safe by construction: only processes whose `--user-data-dir` is inside adb's
    managed namespace (`~/.ai-dev-browser/profiles/...` or the temp prefix
    `ai_dev_browser_*`) AND have no live debug owner are eligible. Your Chrome
    (any other user-data-dir) is structurally never a target.

    Args:
        scope: What to reap (REQUIRED — no blanket default):
            "temp" → orphan throwaway Chromes (temp profiles);
            "profile" → orphans of one named `profile` (requires `profile`);
            "workspace" → all orphans of the current workspace's profiles.
        profile: Workspace profile name — required when scope="profile".
        dry_run: If True, return what WOULD be killed (`would_kill`) without
            killing anything.

    Returns:
        dict with `scope`, `dry_run`; on a real run `killed` (PIDs), `count`,
        `profile_dirs`; on dry_run `would_kill` (list of {pid, user_data_dir})
        and `count`.

    Failure:
        Requires the `cleanup` extra for psutil: pip install
        'ai-dev-browser[cleanup]'. scope="profile" with no `profile` name is a
        usage error — pass the profile to scope to, or use scope="workspace".
    """
    _require_psutil()

    if scope == "profile":
        if not profile:
            raise ValueError(
                "scope='profile' requires a profile name (which profile's "
                "orphans to reap). Pass profile=..., or use scope='workspace'."
            )
        target = _normalize_path(str(get_workspace_profile_dir(profile)))

        def in_scope(udd_norm: str) -> bool:
            return udd_norm == target
    elif scope == "temp":

        def in_scope(udd_norm: str) -> bool:
            return Path(udd_norm).name.startswith(DEFAULT_PROFILE_PREFIX)
    elif scope == "workspace":
        ws_root = _normalize_path(str(DEFAULT_PROFILE_DIR / get_workspace_slug()))

        def in_scope(udd_norm: str) -> bool:
            return udd_norm.startswith(ws_root)
    else:
        raise ValueError(
            f"scope must be one of 'temp' / 'profile' / 'workspace', got {scope!r}"
        )

    orphans = [
        c
        for c in list_chromes(all_workspaces=True)
        if c["origin"] == "adb-orphan"
        and c["user_data_dir"]
        and in_scope(_normalize_path(c["user_data_dir"]))
    ]

    if dry_run:
        return {
            "scope": scope,
            "dry_run": True,
            "would_kill": [
                {"pid": c["pid"], "user_data_dir": c["user_data_dir"]} for c in orphans
            ],
            "count": len(orphans),
        }

    killed: list[int] = []
    profile_dirs_cleaned: set[str] = set()
    for c in orphans:
        if _kill_process_tree(c["pid"]):
            killed.append(c["pid"])
            if c["user_data_dir"]:
                profile_dirs_cleaned.add(c["user_data_dir"])

    return {
        "scope": scope,
        "dry_run": False,
        "killed": killed,
        "count": len(killed),
        "profile_dirs": sorted(profile_dirs_cleaned),
    }
