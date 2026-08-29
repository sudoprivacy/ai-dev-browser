"""Browser lifecycle management operations."""

import asyncio
import os
import time
from pathlib import Path

from . import registry
from .chrome import launch_chrome
from .config import (
    DEFAULT_PROFILE_PREFIX,
    DEFAULT_REUSE_STRATEGY,
    ReuseStrategy,
    get_workspace_profile_dir,
)
from .connection import graceful_close_browser
from .port import (
    _cleanup_temp_profile,
    _query_chrome_guid,
    _query_chrome_user_data_dir,
    find_debug_chromes,
    find_workspace_chromes,
    get_available_port,
    get_pid_on_port,
    is_port_in_use,
)
from .process import _kill_process_tree


def _find_chrome_using_profile(profile_dir: Path) -> tuple[int, int | None] | None:
    """Find a debugging Chrome running under the given profile's user-data-dir.

    Scans the debug port range and matches each Chrome's --user-data-dir
    (resolved from the instance registry, falling back to the CDP cmdline)
    against the profile directory. Registry-backed so it works under stealth,
    where Browser.getBrowserCommandLine returns nothing.

    Returns:
        (port, pid) tuple if found, None otherwise.
    """
    target = os.path.normcase(os.path.normpath(str(profile_dir)))
    for port, pid, _ws in find_debug_chromes():
        udd = _query_chrome_user_data_dir(port)
        if udd and os.path.normcase(os.path.normpath(udd)) == target:
            return (port, pid)
    return None


def _find_reusable_chrome(profile: str | None = None) -> int | None:
    """Find a debugging Chrome in the current workspace to reuse.

    When `profile` is given, only reuse a Chrome already using that
    profile's user-data-dir — otherwise two browser_start calls with
    different profiles would silently share the same Chrome, defeating
    per-profile isolation (e.g. a parallel worker pool).

    When `profile` is None the caller has no profile preference, so any
    idle debugging Chrome in this workspace is reused (legacy behaviour
    for default invocations).

    Returns:
        Port number if a suitable Chrome is found, None otherwise.
    """
    if profile is not None:
        user_data_dir = get_workspace_profile_dir(profile)
        existing = _find_chrome_using_profile(user_data_dir)
        return existing[0] if existing else None

    for port, _pid in find_workspace_chromes():
        return port
    return None


def _env_headless_default() -> bool | str:
    """Read AI_DEV_BROWSER_HEADLESS env var. Accepts:
    - "1" / "true"       → True (= "new")
    - "new" / "old"      → that literal string (selects mode)
    - anything else / "" → False
    """
    raw = os.environ.get("AI_DEV_BROWSER_HEADLESS", "").lower()
    if raw in ("new", "old"):
        return raw
    return raw in ("1", "true")


def browser_start(
    port: int | None = None,
    headless: bool | str = None,  # type: ignore[assignment]
    url: str | None = None,
    profile: str | None = None,
    temp: bool = False,
    reuse: ReuseStrategy = DEFAULT_REUSE_STRATEGY,
    startup_timeout: float = 30.0,
    extra_args: list[str] | None = None,
    override_default_args: dict[str, str | None] | None = None,
    silent_stderr: bool = False,
    stealth: bool = True,
) -> dict:
    """Start a browser instance — ISOLATED and STEALTH by default.

    With no `profile`, each call is a throwaway isolated session: its own port,
    a temporary profile, and no reuse. That's the safe default — automation
    never lands on tabs another session or agent left open in a shared Chrome
    (the failure mode of reusing a persistent Chrome + guessing the active tab).

    Name a `profile` to opt into persistence: a stable per-profile data dir
    (login/cookies survive across runs) that same-profile calls reuse. Different
    profiles never share a Chrome, so profile is also the parallel-worker
    isolation boundary. `cookies_save` / `cookies_load` carry login into an
    otherwise ephemeral session without a named profile.

    Args:
        port: Debug port (auto-assigned if None)
        headless: Run in headless mode. Accepts `False` (default,
            windowed), `True` / `"new"` (new headless: full Chrome
            architecture, supports automation), or `"old"` (legacy
            headless — use when CI fails with "Multiple targets are not
            supported in headless mode" under the new mode). `None`
            falls back to the `AI_DEV_BROWSER_HEADLESS` env var:
            `1`/`true` → True, `new`/`old` → that literal mode, anything
            else → False.
        url: Initial URL to open (default: about:blank)
        profile: Named profile for a PERSISTENT session (login survives,
            reusable, per-profile isolated). Omit for the isolated ephemeral
            default.
        temp: Force a temporary profile. Implied when no `profile` is named,
            so the default is already isolated; pass it explicitly only to
            override a configured profile.
        reuse: "none" (always new) or "any" (reuse an idle same-profile
            Chrome, default). Only consulted for a named profile — an
            ephemeral session never reuses.
        startup_timeout: Seconds to wait for Chrome to bind its debug port
            after spawn. Default 30s covers cold-start on slow Windows
            machines (fresh profile init + Defender scan + I/O contention
            from the user's main Chrome). Bump higher if you see
            "started but port not listening" on a known-good environment;
            lower it (e.g. 5s) for headless CI where startup is fast and
            you want to fail loud quickly.
        extra_args: Additional Chrome command-line flags appended after
            the defaults. Plain passthrough to `launch_chrome`.
        override_default_args: Override or remove default Chrome flags.
            Dict mapping flag to new value, or None to remove. Example:
            `{"--disable-extensions": None}` removes it;
            `{"--remote-allow-origins": "localhost"}` replaces its value.
            On CLI: `--override-default-args '{"--flag": null}'`.
        silent_stderr: If True, route Chrome's stderr to DEVNULL instead
            of PIPE. Use in long-running / multi-agent scenarios where
            you don't want Chrome's GPU/Crashpad/V8 subsystems filling
            the pipe buffer. Trade-off: loses Chrome's exit-time stderr
            in the error path (falls back to generic "Chrome exited
            silently"). See `launch_chrome` docstring for details.
        stealth: Launch without automation markers (default: True). Drops
            `--enable-automation` and `--disable-blink-features=Automation
            Controlled`, so navigator.webdriver=false and no info/warning
            bars — a real-browser fingerprint that bot detection
            (Google/Cloudflare) is far less likely to flag. `False`
            restores both flags (legacy behavior). Workspace/profile
            discovery is registry-backed and does not rely on these, so
            stealth stays on with no loss of function.

    Returns:
        dict with port, pid, headless, url, profile, reused, message
    """
    # Isolation by default: an unnamed session has nothing to persist and must
    # not reuse a shared Chrome (where it could act on another session's tabs),
    # so run it as a throwaway temp session. A named profile is the explicit
    # opt-in to persistence + reuse.
    if profile is None and not temp:
        temp = True

    # Try to reuse an existing Chrome. Profile-aware: if the caller asked
    # for a specific profile we must not hand back a Chrome running a
    # different profile (that would break parallel workers using distinct
    # profiles for isolation). `temp=True` always wants a fresh session,
    # so skip reuse entirely for that.
    if reuse != "none" and not temp:
        reused_port = _find_reusable_chrome(profile=profile)
        if reused_port:
            pid = get_pid_on_port(reused_port)
            return {
                "port": reused_port,
                "pid": pid,
                "profile": profile or "default",
                "reused": True,
                "message": f"Reusing existing Chrome on port {reused_port}",
            }

    # No reusable Chrome found above (or reuse was skipped for
    # temp/profile/none). Top-level has already decided reuse semantics, so
    # ask get_available_port for a fresh port only — otherwise it would
    # silently hand back the same workspace Chrome we just declined to
    # reuse.
    if port is None:
        port = get_available_port(reuse=False)
    else:
        # User specified a port - check if it's available
        if is_port_in_use(port=port):
            pid = get_pid_on_port(port)
            return {
                "error": f"Port {port} is already in use (PID: {pid}). "
                f"Use a different port or stop the existing process."
            }

    # Determine user data directory
    if temp:
        # Create the throwaway profile dir HERE (not inside launch_chrome) so we
        # know its path and can record it in the instance registry — orphan
        # cleanup relies on knowing every live Chrome's user-data-dir, and under
        # stealth it can't read it back from the CDP command line. Unique per
        # launch (mkdtemp), same `{prefix}{port}_` naming _cleanup_temp_profile
        # globs on stop.
        import tempfile

        user_data_dir = Path(
            tempfile.mkdtemp(prefix=f"{DEFAULT_PROFILE_PREFIX}{port}_")
        )
        profile_name = "(temp)"
    else:
        profile_name = profile or "default"
        user_data_dir = get_workspace_profile_dir(profile_name)
        user_data_dir.mkdir(parents=True, exist_ok=True)

        # Safety: if another Chrome is already using this profile, reuse it
        # (launching two Chromes with the same user-data-dir causes crashes)
        existing = _find_chrome_using_profile(user_data_dir)
        if existing:
            existing_port, existing_pid = existing
            return {
                "port": existing_port,
                "pid": existing_pid,
                "profile": profile_name,
                "reused": True,
                "message": f"Profile '{profile_name}' already in use. Reusing Chrome on port {existing_port}.",
            }

    # Launch Chrome — resolve env-var fallback if caller didn't pass headless.
    start_url = url or "about:blank"
    headless_resolved = _env_headless_default() if headless is None else headless
    process = launch_chrome(
        port=port,
        headless=headless_resolved,
        start_url=start_url,
        user_data_dir=str(user_data_dir),
        extra_args=extra_args,
        override_default_args=override_default_args,
        silent_stderr=silent_stderr,
        stealth=stealth,
    )

    # Wait for Chrome to bind its debug port.
    poll_interval = 0.2
    elapsed = 0.0
    while elapsed < startup_timeout:
        if is_port_in_use(port=port):
            break
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr else ""
            # Provide more helpful error message
            if not stderr:
                stderr = (
                    "Chrome exited silently. Possible causes:\n"
                    "  - Another Chrome is using this profile\n"
                    "  - Profile directory is corrupted\n"
                    "  - Insufficient permissions"
                )
            return {"error": f"Chrome process exited unexpectedly: {stderr}"}
        time.sleep(poll_interval)
        elapsed += poll_interval
    else:
        # Timed out. Chrome may still be starting (slow cold-start scenarios)
        # — but if we leave it alive it holds the profile's lockfile, and the
        # next browser_start with the same profile fails on lock contention.
        # Kill the whole process tree so the profile is released; caller can
        # retry with a higher startup_timeout.
        orphan_pid = process.pid
        _kill_process_tree(orphan_pid)
        return {
            "error": (
                f"Chrome started (PID {orphan_pid}) but port {port} not "
                f"listening after {startup_timeout}s — process killed to "
                f"release profile lockfile. Retry with startup_timeout=<larger> "
                f"if your environment is slow (Windows + main Chrome running, "
                f"first-time profile init, AV scanning, etc.)."
            ),
            "pid": orphan_pid,
        }

    # Record this instance so workspace/profile discovery can find it WITHOUT
    # reading Chrome's command line over CDP (which needs --enable-automation,
    # off under stealth). Keyed later by the browser GUID from /json/version so
    # a reused port can't alias a stale record. Best-effort — a failed write
    # only degrades to the cmdline fallback.
    registry.register_instance(
        port=port,
        guid=_query_chrome_guid(port),
        workspace=os.getcwd(),
        pid=process.pid,
        user_data_dir=str(user_data_dir),
    )

    return {
        "port": port,
        "pid": process.pid,
        "headless": headless,
        "url": start_url,
        "profile": profile_name,
        "reused": False,
        "message": f"Browser started on port {port}",
    }


def _graceful_stop(port: int, pid: int, timeout: float = 5.0) -> dict:
    """Gracefully stop a Chrome instance via CDP Browser.close().

    Sends Browser.close() which flushes cookies/profile data, then waits
    for the process to exit. Falls back to force-kill if graceful fails.

    Returns:
        dict with port, pid, and method used ("graceful" or "force").
    """
    # Try graceful shutdown via CDP. Detect whether we're already inside a
    # running event loop BEFORE constructing the coroutine — otherwise
    # calling graceful_close_browser(port=port) eagerly creates a coroutine
    # object, and if asyncio.run rejects it (in-loop), the coroutine is
    # never awaited and Python emits
    # "RuntimeWarning: coroutine ... was never awaited".
    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False

    try:
        if in_loop:
            # Can't asyncio.run here — offload to a thread with its own loop
            import concurrent.futures

            def _run_close():
                return asyncio.run(graceful_close_browser(port=port))

            with concurrent.futures.ThreadPoolExecutor() as pool:
                sent = pool.submit(_run_close).result(timeout=timeout)
        else:
            sent = asyncio.run(graceful_close_browser(port=port))
    except Exception:
        sent = False

    if sent:
        # Wait for process to exit
        elapsed = 0.0
        poll_interval = 0.2
        while elapsed < timeout:
            if not is_port_in_use(port=port):
                _cleanup_temp_profile(port)
                registry.unregister_instance(port)
                return {"port": port, "pid": pid, "method": "graceful"}
            time.sleep(poll_interval)
            elapsed += poll_interval

    # Graceful failed or timed out — force kill
    _kill_process_tree(pid)
    _cleanup_temp_profile(port)
    registry.unregister_instance(port)
    return {"port": port, "pid": pid, "method": "force"}


def browser_stop(
    port: int | None = None,
    stop_all: bool = False,
) -> dict:
    """Stop browser instance(s).

    Uses CDP Browser.close() for graceful shutdown (flushes cookies to
    profile SQLite). Falls back to force-kill if graceful fails.

    Args:
        port: Port of browser to stop
        stop_all: Stop all debugging Chrome instances

    Returns:
        dict with stopped status, count, browsers list
    """
    if not port and not stop_all:
        return {"error": "Please specify port or stop_all"}

    stopped = []

    if stop_all:
        for p, pid, _ws in find_debug_chromes():
            if pid is None:
                continue
            try:
                result = _graceful_stop(p, pid)
                stopped.append(result)
            except Exception:
                pass
    else:
        pid = get_pid_on_port(port)
        if pid:
            result = _graceful_stop(port, pid)
            stopped.append(result)

    return {
        "stopped": True,
        "count": len(stopped),
        "browsers": stopped,
    }


def browser_list(all_workspaces: bool = False) -> dict:
    """List debugging Chrome instances.

    By default, shows only Chromes belonging to the current workspace.
    Use all_workspaces=True to see all debugging Chromes.

    Args:
        all_workspaces: Show Chromes from all workspaces (default: current only)

    Returns:
        dict with browsers list and count
    """
    browsers = []

    if all_workspaces:
        for p, pid, workspace in find_debug_chromes():
            info: dict = {
                "port": p,
                "pid": pid,
            }
            if workspace:
                info["workspace"] = workspace
            browsers.append(info)
    else:
        for p, pid in find_workspace_chromes():
            browsers.append(
                {
                    "port": p,
                    "pid": pid,
                }
            )

    return {
        "browsers": browsers,
        "count": len(browsers),
    }
