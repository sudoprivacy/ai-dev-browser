"""Browser lifecycle management operations."""

import asyncio
import os
import time
from pathlib import Path

from typing import Literal

from . import registry
from .chrome import launch_chrome
from .config import (
    DEFAULT_PROFILE_PREFIX,
    DEFAULT_REUSE_STRATEGY,
    ReuseStrategy,
    get_workspace_profile_dir,
)
from .connection import connect_browser, graceful_close_browser
from .extension import (
    EXTENSION_BRIDGE_PORT,
    extension_dir,
    extension_load_instructions,
)
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

    This **launches** a new browser. To drive an ALREADY-RUNNING one instead,
    use `browser_connect` — an existing CDP Chrome by port, or your **real,
    logged-in** browser via `browser_connect --transport extension` (real
    profile, logins, device-trust; for Google SSO / sites that block fresh
    profiles). Reusing your real login is `browser_connect --transport
    extension`, not a fresh `browser_start`.

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


async def browser_connect(
    transport: Literal["cdp", "extension"] = "cdp",
    port: int | None = None,
) -> dict:
    """Use when: you want to drive an ALREADY-RUNNING browser — a CDP Chrome
    (`transport=cdp`, the default) or your REAL logged-in browser via the
    extension (`transport=extension`). Returns `{transport, connected, ...}` so
    you can act immediately (or, if not connected, exact setup steps).

    Two transports, deliberately different tools than `browser_start`:
    - **cdp** (default): attaches to a CDP Chrome by `--port` (or auto-detects
      the workspace one). Autonomous, headless-capable, parallel — the 90% case.
    - **extension**: drives your **real** Chrome (your profile, logins,
      device-trust) through the ai-dev-browser bridge extension — the way to
      look human on hardened sites (Google SSO). It drives a dedicated
      automation tab and FOLLOWS the popups/new tabs your automation opens (an
      OAuth account-chooser, a magic-link tab), so multi-tab logins don't stall
      — reach them with `tab_list`/`tab_switch` or `--tab-url`, exactly like cdp;
      your own tabs are never touched. **Not autonomous**: it needs the
      extension installed + enabled and Chrome running, and can't run headless
      or parallel. If it isn't set up, this returns the exact
      `setup_instructions` to hand the user (Chrome blocks command-line
      loading, so a person loads it once).

    For a FRESH, isolated, disposable browser instead of attaching to an
    existing one, use `browser_start` (it launches one; this only attaches).

    Args:
        transport: "cdp" (attach to a CDP Chrome, default) or "extension"
            (drive your real browser via the bridge extension). Settable
            process-wide via `AI_DEV_BROWSER_TRANSPORT`.
        port: CDP debug port to attach to (cdp only; auto-detects if omitted).

    Which profile (extension mode): the extension drives the Chrome **profile it
    was loaded into**. On success this returns `account` (the profile's signed-in
    email) so you know WHICH browser/account you're driving — if it's the wrong
    one, load & enable the extension in the target profile instead. There's no
    remote profile-switch: the extension is per-profile.

    Args-note: extension mode auto-starts its local bridge daemon (no manual
    step); you only ever load the extension once, by hand.

    Returns:
        dict with `transport`, `connected`. cdp+connected: `port, tab_count,
        tabs`. extension+connected: `account, tab_count, tabs`. Not connected:
        `setup_instructions` + `extension_dir` (and `bridge_running` once the
        daemon is up), or the cdp connect error.

    Failure:
        cdp + not connected → no Chrome on that port; `browser_start` to launch
        one. extension: the bridge daemon is auto-started, so `connected: false`
        with `bridge_running: true` means NO extension has dialed in — either the
        ai-dev-browser extension isn't loaded/enabled in a running Chrome (follow
        `setup_instructions`, load `extension_dir`), or you just (re)loaded it —
        wait a few seconds, it auto-reconnects, and retry. `bridge_running` absent
        means the daemon itself couldn't start (see `error`).
    """
    if transport == "extension":
        from .ext_bridge import ensure_bridge_running, wait_for_extension

        # Auto-start the bridge daemon — no manual ensure_bridge_running() dance;
        # extension mode should be as out-of-box as CDP mode's auto-connect.
        if not ensure_bridge_running():
            return {
                "transport": "extension",
                "connected": False,
                "retryable": False,  # daemon won't start — an environment issue
                "extension_dir": str(extension_dir()),
                "error": (
                    "Could not start the extension bridge daemon on port "
                    f"{EXTENSION_BRIDGE_PORT}."
                ),
            }
        # Give a just-(re)loaded extension a few seconds to dial back in.
        status = await wait_for_extension(timeout=4.0)
        if status and status.get("extension_connected"):
            # Build the real BrowserClient over the bridge and list its tabs —
            # same shape as cdp, and it proves the multiplexer end to end.
            tabs: list[str] = []
            try:
                from .connection import connect_extension

                browser = await connect_extension()
                tabs = [getattr(t._target, "url", "") or "" for t in browser.tabs]
            except Exception:
                pass  # connected per the daemon; tab list is best-effort
            # Report WHICH profile/account we're driving — the extension runs in
            # the profile it was loaded into.
            return {
                "transport": "extension",
                "connected": True,
                "account": status.get("account"),
                "tab_count": len(tabs),
                "tabs": tabs,
                "bridge_port": EXTENSION_BRIDGE_PORT,
            }
        # Daemon is up, but no extension has dialed in yet — loading/enabling it
        # (or waiting out a just-reload) and retrying is the fix.
        return {
            "transport": "extension",
            "connected": False,
            "retryable": True,
            "bridge_running": True,
            "extension_dir": str(extension_dir()),
            "setup_instructions": extension_load_instructions(),
        }

    # cdp
    try:
        browser = await connect_browser(port=port)
    except Exception as e:
        # Not retryable as-is: no Chrome on that port — launch one (browser_start)
        # or fix the port. The Failure: hint says so.
        return {
            "transport": "cdp",
            "connected": False,
            "retryable": False,
            "error": str(e),
        }
    tabs = [getattr(t._target, "url", "") or "" for t in browser.tabs]
    return {
        "transport": "cdp",
        "connected": True,
        "port": browser.port,
        "tab_count": len(tabs),
        "tabs": tabs,
    }


def browser_disconnect() -> dict:
    """Use when: you're done driving your real browser, or want to cut
    automation's access to it NOW. Emergency stop for the **extension**
    transport — drops the local bridge so ai-dev-browser can no longer reach
    your live browser. Returns `{stopped, was_running}`.

    The extension detaches once the bridge is gone. For a HARD kill (revoke the
    debugger permission entirely), also toggle off or 移除 the "AI Dev Browser —
    bridge" extension in chrome://extensions — that's the one-click hardware
    switch. CDP mode has nothing to disconnect (connections are per-call); use
    `browser_stop` to stop a launched Chrome.
    """
    from .ext_bridge import EXTENSION_BRIDGE_PORT, bridge_is_up

    was_running = bridge_is_up(EXTENSION_BRIDGE_PORT)
    if was_running:
        pid = get_pid_on_port(EXTENSION_BRIDGE_PORT)
        if pid:
            _kill_process_tree(pid)
    return {"stopped": True, "was_running": was_running}


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
