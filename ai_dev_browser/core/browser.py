"""Browser lifecycle management operations."""

import asyncio
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from typing import Literal

from . import registry
from . import _session
from ._browser_guidance import mode_guidance
from .chrome import launch_chrome
from .config import (
    DEFAULT_PROFILE_PREFIX,
    DEFAULT_REUSE_STRATEGY,
    ReuseStrategy,
    get_workspace_profile_dir,
    resolve_startup_timeout,
)
from .connection import connect_browser, graceful_close_browser
from .extension import (
    EXTENSION_BRIDGE_PORT,
    extension_dir,
    extension_load_instructions,
    extension_version_info,
    bridge_version_info,
    query_extension_version,
)
from .port import (
    _cleanup_temp_profile,
    _open_chrome_http,
    _query_chrome_guid,
    _query_chrome_version,
    _query_chrome_user_data_dir,
    find_debug_chromes,
    find_workspace_chromes,
    get_available_port,
    get_pid_on_port,
    is_port_in_use,
)
from .process import _kill_process_tree, no_console_options


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


def _proxy_in_args(extra_args: list[str] | None) -> bool:
    """True if a `--proxy-server=...` flag is present in extra_args (the trigger
    for default timezone/geo matching)."""
    return any(
        isinstance(a, str) and a.startswith("--proxy-server=")
        for a in (extra_args or [])
    )


def _with_lang_arg(
    extra_args: list[str] | None, locale: str | None
) -> list[str] | None:
    """Ensure a `--lang=<locale>` launch flag when a `locale` is requested.

    navigator.language / navigator.languages are fixed at renderer launch by
    Chrome's UI locale, which ONLY the `--lang` flag sets — a per-session
    `Emulation.setLocaleOverride` moves `Intl` but never `navigator.language`.
    So an explicit locale has to go in at launch, not just through the per-call
    re-apply. A `--lang` the caller already passed wins (returned untouched);
    Chrome maps the value to its nearest supported UI locale (e.g. en-SG→en-GB),
    so the landed navigator.language can differ from the request."""
    if not locale:
        return extra_args
    args = list(extra_args or [])
    if any(isinstance(a, str) and a.startswith("--lang=") for a in args):
        return args
    args.append(f"--lang={locale}")
    return args


def _resolve_do_match(
    explicit_identity: bool, match_proxy: bool | None, extra_args: list[str] | None
) -> bool:
    """Whether to auto-derive timezone/geo from the proxy egress. Explicit
    tz/geo always wins (no lookup); else the `match_proxy` arg; else the env;
    else the DEFAULT — on when a `--proxy-server` is present."""
    from .config import resolve_match_proxy_env

    if explicit_identity:
        return False
    if match_proxy is not None:
        return match_proxy
    env_match = resolve_match_proxy_env()
    return env_match if env_match is not None else _proxy_in_args(extra_args)


async def _read_navigator_language(
    port: int, target_id: str | None = None
) -> str | None:
    """The locale actually in effect — `navigator.language` read back from the
    launched browser. Chrome maps --lang to its nearest supported UI locale, so
    this is what a site sees, which may differ from the requested locale.
    Best-effort: None if the browser can't be reached."""
    import contextlib

    from .connection import connect_browser, get_active_tab

    browser = None
    try:
        browser = await connect_browser(port=port)
        tab = (
            next(t for t in browser.tabs if str(t._target.target_id) == target_id)
            if target_id
            else await get_active_tab(browser)
        )
        val = await tab.evaluate("navigator.language")
        return val if isinstance(val, str) and val else None
    except Exception:
        return None
    finally:
        # Close the CDP connection (NOT the Chrome process) so its cache entry —
        # bound to this ephemeral _run_coro loop — doesn't linger and break a
        # same-process async consumer that connects next (same guard
        # derive_from_proxy uses).
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()


def _run_coro(coro):
    """Run a coroutine from the sync browser_start: asyncio.run normally, or a
    worker thread if a loop is already running (sync fn called from async)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(coro)).result()


@mode_guidance
def browser_start(
    port: int | None = None,
    headless: bool | str = None,  # type: ignore[assignment]
    url: str | None = None,
    profile: str | None = None,
    temp: bool = False,
    reuse: ReuseStrategy = DEFAULT_REUSE_STRATEGY,
    startup_timeout: float | None = None,
    extra_args: list[str] | None = None,
    override_default_args: dict[str, str | None] | None = None,
    silent_stderr: bool = False,
    stealth: bool = True,
    timezone: str | None = None,
    geo: str | None = None,
    locale: str | None = None,
    match_proxy: bool | None = None,
    transport: Literal["cdp", "extension"] = "cdp",
    chrome_path: str | None = None,
    user_data_dir: str | None = None,
    profile_directory: str = "Default",
    display: str | None = None,
) -> dict:
    """Use when: you need a new isolated CDP session or explicitly launch a configured extension profile; returns session_id and actual capabilities.

    {mode_guidance}

    With no `profile`, each call is a throwaway isolated session: its own port,
    a temporary profile, and no reuse. That's the safe default — automation
    never lands on tabs another session or agent left open in a shared Chrome
    (the failure mode of reusing a persistent Chrome + guessing the active tab).

    Name a `profile` to opt into persistence: a stable per-profile data dir
    (login/cookies survive across runs) that same-profile calls reuse. Different
    profiles never share a Chrome, so profile is also the parallel-worker
    isolation boundary. `cookies_save` / `cookies_load` carry login into an
    otherwise ephemeral session without a named profile.

    With transport=extension, choose an existing user_data_dir and
    profile_directory that already has the bridge installed/enabled. A busy
    data directory returns conflict; use browser_connect instead. Startup
    changes neither installed extensions nor profile preferences. A failed
    handshake leaves the explicitly launched Chrome running and reports its PID.
    Read extension_warning before input: an attached extension's unknown or
    mismatched version needs an ordinary update/reload and a fresh connection.
    Fresh CDP launches prepare their owned page before the initial URL navigation.

    Proxy consistency (automatic): if `extra_args` carries a `--proxy-server`
    and you don't pass an explicit `timezone`/`geo`, this auto-aligns the
    browser's timezone + geolocation with the proxy's egress (a Tokyo IP with a
    Shanghai clock is a classic anti-fraud tell). The return reports
    `identity_consistent` + the effective `timezone`/`geolocation`/`egress_ip`,
    so you don't need to read them back yourself. Language is left alone — set
    `locale` only when you mean to. See `match_proxy`.

    Args:
        transport: "cdp" (isolated automation, default) or "extension"
            (explicitly launch an already configured real Chrome/profile).
        chrome_path: Chrome executable to launch; otherwise find_chrome resolves it.
        display: Optional local X11 display ID, such as ":2", for a host-owned
            GUI. Passed only to this Chrome child; the calling process keeps
            its DISPLAY unchanged. Omit to use the existing desktop display.
        user_data_dir: Existing Chrome user-data root, required for extension
            startup. CDP uses temp/named adb profiles; this option is extension only.
        profile_directory: Chrome folder inside user_data_dir, e.g. "Default"
            or "Profile 1". Extension only; different folders share a process lock.
        port: Debug port (auto-assigned if None)
        headless: Run in headless mode. Accepts `False` (default,
            windowed), `True` / `"new"` (new headless: full Chrome
            architecture, supports automation), or `"old"` (legacy
            headless — use when CI fails with "Multiple targets are not
            supported in headless mode" under the new mode). `None`
            falls back to the `AI_DEV_BROWSER_HEADLESS` env var:
            `1`/`true` → True, `new`/`old` → that literal mode, anything
            else → False. CLI: `--headless true` / `--headless false`,
            or `--headless new` / `--headless old` (an explicit value is required).
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
        startup_timeout: Seconds to wait for Chrome's debug port, CDP browser
            identity, owned page/network context and initial navigation, or
            the extension handshake.
            `None` resolves to the
            `AI_DEV_BROWSER_STARTUP_TIMEOUT` env var, else 30s — which
            covers cold-start on slow Windows machines (fresh profile init
            + Defender scan + I/O contention from the user's main Chrome).
            Bump higher (arg or env) if you see "started but port not
            listening" on a known-slow host (a loaded CI runner); lower it
            (e.g. 5s) for fast headless CI where you want to fail loud quickly.
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
        timezone: IANA timezone (e.g. "Asia/Tokyo") to override the browser's
            timezone. Re-asserted on every tool call, so it holds across new
            tabs and navigation — unlike a one-shot `cdp_send`, whose Emulation
            override dies with its session. Use this when a `--proxy-server`
            routes your egress to another country, so the IP and the timezone
            don't contradict (a Tokyo IP with an Asia/Shanghai clock is a
            classic anti-fraud tell).
        geo: "lat,lon" (e.g. "35.68,139.69") to override geolocation (granted,
            so a site that reads it sees the mocked position). Same re-assert-
            every-call persistence as `timezone`. Pair with `timezone` to keep
            all location signals consistent with the proxy egress.
        locale: ICU/BCP-47 locale (e.g. "ja-JP") to override — OFF by default
            and ON PURPOSE. Timezone/geo are LOCATION signals (align them with
            the proxy); language is an IDENTITY signal, not location — a zh-CN
            user behind a Tokyo IP is normal, and auto-switching to ja-JP would
            make a fresh inconsistency and turn every site Japanese. So set
            `locale` only when you explicitly want to. When set, it drives BOTH
            the `--lang` launch flag (which is what actually moves
            `navigator.language` / `navigator.languages`) and a per-call `Intl`
            override. Chrome maps `--lang` to its nearest supported UI locale, so
            the landed `navigator.language` can differ from the request (en-SG →
            en-GB); the return reports what actually landed (see below).
        match_proxy: Auto-derive `timezone` + `geolocation` from the egress.
            Default (None) is **ON when a `--proxy-server` is in `extra_args`
            and no explicit `timezone`/`geo` is given** — so even an agent that
            never heard of this gets a consistent identity for free. It does one
            geo-IP lookup THROUGH the browser (so via the proxy — the host IP is
            never exposed); explicit `timezone`/`geo` skip the lookup entirely.
            `True`/`False` force it; also `AI_DEV_BROWSER_MATCH_PROXY`, and the
            endpoint is `AI_DEV_BROWSER_GEO_ENDPOINT`. If the lookup fails the
            launch still succeeds but the return flags it (see below).

    Returns:
        dict with port, pid, headless, url, profile, reused, message. chrome_path
        is the observed process executable; launch_chrome_path is the original
        spawn executable used for restart, which can differ on macOS. With an
        identity override: `identity_consistent: true` + the effective
        `timezone` / `geolocation` / `locale` (+ `egress_ip` when matched), so
        you confirm consistency in one call. `locale` is the locale that actually
        LANDED (`navigator.language` read back), plus `locale_requested` when
        Chrome normalized it to a different UI locale. If matching was attempted
        but the egress lookup failed: `identity_consistent: false` +
        `identity_warning` (the browser launched, but IP and location signals may
        be inconsistent — pass explicit `timezone`/`geo` or check the proxy).
    Failure:
        Check error_code and actual resources. Busy profiles need an explicit
        browser_connect request. Install/enable the bridge in the selected
        profile before extension startup. Configure a GUI or explicitly choose
        a supported headless mode. Never switch transport/profile, restart, or
        replay input implicitly after failure.
    """
    start_options = dict(locals())
    if display is not None and (
        not isinstance(display, str) or not re.fullmatch(r":\d+(?:\.\d+)?", display)
    ):
        return _session.failure(
            "validation",
            "An explicit display must be a local X11 display ID",
            transport=transport,
        )
    startup_timeout = resolve_startup_timeout(startup_timeout)
    if transport == "extension":
        if (
            port is not None
            or profile is not None
            or temp
            or override_default_args
            or timezone
            or geo
            or locale
            or match_proxy is not None
        ):
            return _session.failure(
                "validation",
                "Extension startup uses user_data_dir/profile_directory; CDP port, named/temp profiles, default-flag overrides and identity emulation do not apply",
                transport="extension",
            )
        from ._extension_lifecycle import start

        return _run_coro(
            start(
                user_data_dir=user_data_dir,
                profile_directory=profile_directory,
                chrome_path=chrome_path,
                headless=_env_headless_default() if headless is None else headless,
                url=url,
                startup_timeout=startup_timeout,
                extra_args=extra_args,
                display=display,
            )
        )
    if (
        transport != "cdp"
        or user_data_dir is not None
        or profile_directory != "Default"
    ):
        return _session.failure(
            "validation",
            "CDP startup uses temp/named adb profiles; user_data_dir/profile_directory are extension-only",
            transport=transport,
        )
    effective_headless = _env_headless_default() if headless is None else headless
    if not effective_headless:
        import sys

        if sys.platform.startswith("linux") and not (
            display or os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        ):
            return _session.failure(
                "unsupported",
                "Windowed Chrome requires DISPLAY or WAYLAND_DISPLAY; configure a GUI or choose headless explicitly",
                transport="cdp",
            )

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
            return _describe_cdp(
                {
                    "port": reused_port,
                    "pid": pid,
                    "profile": profile or "default",
                    "reused": True,
                    "message": f"Reusing existing Chrome on port {reused_port}",
                }
            )

    # No reusable Chrome found above (or reuse was skipped for
    # temp/profile/none). Top-level has already decided reuse semantics, so
    # ask get_available_port for a fresh port only — otherwise it would
    # silently hand back the same workspace Chrome we just declined to
    # reuse.
    auto_port = port is None
    if auto_port:
        # randomize: spread fresh launches across the band so a just-released
        # port isn't immediately reused (Windows can transiently reject re-bind).
        port = get_available_port(reuse=False, randomize=True)
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

        cdp_data_dir = Path(tempfile.mkdtemp(prefix=f"{DEFAULT_PROFILE_PREFIX}{port}_"))
        profile_name = "(temp)"
    else:
        profile_name = profile or "default"
        cdp_data_dir = get_workspace_profile_dir(profile_name)
        cdp_data_dir.mkdir(parents=True, exist_ok=True)

        # Safety: if another Chrome is already using this profile, reuse it
        # (launching two Chromes with the same user-data-dir causes crashes)
        existing = _find_chrome_using_profile(cdp_data_dir)
        if existing:
            existing_port, existing_pid = existing
            return _describe_cdp(
                {
                    "port": existing_port,
                    "pid": existing_pid,
                    "profile": profile_name,
                    "reused": True,
                    "message": f"Profile '{profile_name}' already in use. Reusing Chrome on port {existing_port}.",
                }
            )

    # Launch Chrome, retrying ONCE on a cold-start miss with a fresh port. On a
    # loaded host (esp. Windows: a just-released port transiently rejecting the
    # next bind, a dropped spawn) Chrome can fail to bind its debug port even
    # though nothing is wrong with the request — a relaunch on a different port
    # clears it. Only an auto-assigned port retries (a caller-pinned port must
    # stay put); a temp session gets a fresh dir, a named profile keeps its own.
    start_url = url or "about:blank"
    headless_resolved = _env_headless_default() if headless is None else headless
    # An explicit locale must go in at launch (--lang) to move navigator.language;
    # the per-session setLocaleOverride only covers Intl. See _with_lang_arg.
    extra_args = _with_lang_arg(extra_args, locale)
    poll_interval = 0.2
    max_attempts = 2 if auto_port else 1
    last_error: dict = {}
    process = None

    from typing import Any

    launch_options: dict[str, Any] = {"chrome_path": chrome_path} if chrome_path else {}
    launch_overrides = {"--no-startup-window": "", **(override_default_args or {})}
    if display is not None:
        launch_options["display"] = display
    for attempt in range(max_attempts):
        process = launch_chrome(
            port=port,
            headless=headless_resolved,
            start_url="",
            user_data_dir=str(cdp_data_dir),
            extra_args=extra_args,
            override_default_args=launch_overrides,
            silent_stderr=silent_stderr,
            stealth=stealth,
            **launch_options,
        )

        # Establish this process's browser identity before creating its owned page.
        bound = False
        ready_guid = None
        ready_target = None
        elapsed = 0.0
        wait_started = time.monotonic()
        while elapsed < startup_timeout:
            if is_port_in_use(port=port):
                ready_guid = _query_chrome_guid(port)
                if ready_guid:
                    bound = True
                    break
            if process.poll() is not None:
                stderr = process.stderr.read() if process.stderr else ""
                if not stderr:
                    stderr = (
                        "Chrome exited silently. Possible causes:\n"
                        "  - Another Chrome is using this profile\n"
                        "  - Profile directory is corrupted\n"
                        "  - Insufficient permissions"
                    )
                last_error = {"error": f"Chrome process exited unexpectedly: {stderr}"}
                break
            time.sleep(poll_interval)
            elapsed = time.monotonic() - wait_started
        else:
            # Timed out. Chrome may still be starting, but leaving it alive holds
            # the profile lockfile and blocks the next start — kill the tree so
            # the profile is released, then retry (fresh port) if attempts remain.
            orphan_pid = process.pid
            _kill_process_tree(orphan_pid)
            last_error = {
                "error": (
                    f"Chrome started (PID {orphan_pid}) but port {port} not "
                    f"ready with a CDP browser identity after {startup_timeout}s — process killed to "
                    f"release profile lockfile. Retry with startup_timeout=<larger> "
                    f"if your environment is slow (Windows + main Chrome running, "
                    f"first-time profile init, AV scanning, etc.)."
                ),
                "pid": orphan_pid,
            }

        if bound:
            break

        # Failed this attempt. Make sure the process is dead, then retry on a
        # FRESH port (a lingering/stuck port won't repeat) if attempts remain.
        if process.poll() is None:
            _kill_process_tree(process.pid)
        if attempt < max_attempts - 1:
            port = get_available_port(reuse=False, exclude={port}, randomize=True)
            if temp:
                import tempfile

                cdp_data_dir = Path(
                    tempfile.mkdtemp(prefix=f"{DEFAULT_PROFILE_PREFIX}{port}_")
                )
            continue
        return last_error

    ready_target = None
    start_options["headless"] = headless_resolved
    spawned_args = getattr(process, "args", None)
    if isinstance(spawned_args, (list, tuple)) and spawned_args:
        # Preserve the executable launched when macOS reports a code-sign clone.
        start_options["chrome_path"] = str(spawned_args[0])
    try:
        ready_target = _run_coro(
            _create_startup_page(
                port,
                ready_guid,
                "about:blank",
                max(0.0, startup_timeout - (time.monotonic() - wait_started)),
            )
        )
        _run_coro(
            _prepare_startup_page(
                port,
                ready_target,
                start_url,
                max(0.0, startup_timeout - (time.monotonic() - wait_started)),
            )
        )
    except Exception as error:
        # A lost creation or navigation reply is ambiguous. Retain Chrome and
        # the known target so reconnect can inspect the outcome.
        registry.register_instance(
            port=port,
            guid=ready_guid,
            workspace=os.getcwd(),
            pid=process.pid,
            user_data_dir=str(cdp_data_dir),
        )
        state = {
            "transport": "cdp",
            "port": port,
            "pid": process.pid,
            "browser_closed": False,
            "user_data_dir": str(cdp_data_dir),
            "headless": headless_resolved,
        }
        if ready_target:
            state = _describe_cdp(
                {**state, "automation_target_id": ready_target},
                start_options=start_options,
                guid=ready_guid,
            )
        return _session.failure(
            "transient",
            f"Chrome's initial page could not be confirmed: {str(error) or type(error).__name__}. "
            "Reconnect and inspect its pages before continuing.",
            **state,
        )

    # Record this instance so workspace/profile discovery can find it WITHOUT
    # reading Chrome's command line over CDP (which needs --enable-automation,
    # off under stealth). Keyed later by the browser GUID from /json/version so
    # a reused port can't alias a stale record. Best-effort — a failed write
    # only degrades to the cmdline fallback.
    # Proxy-consistent identity: timezone / geolocation / explicit locale,
    # recorded so get_active_tab re-asserts them every session (they'd otherwise
    # be lost per-call).
    from .identity import build_identity, derive_from_proxy, parse_geo

    identity_warning: str | None = None
    egress_ip: str | None = None
    explicit_identity = bool(timezone or geo)

    # Decide whether to auto-derive location from the proxy egress. Default ON
    # when a --proxy-server is set and no explicit tz/geo is given — so an agent
    # with no context still gets a consistent identity (a proxy that changes the
    # IP but not the clock is a classic anti-fraud tell). Explicit values always
    # win and never trigger a lookup (deterministic, no network).
    do_match = _resolve_do_match(explicit_identity, match_proxy, extra_args)

    if do_match:
        derived = _run_coro(derive_from_proxy(port))
        if derived and derived.get("timezone"):
            timezone = derived["timezone"]
            if derived.get("lat") is not None and derived.get("lon") is not None:
                geo = f"{derived['lat']},{derived['lon']}"
            egress_ip = derived.get("ip")
        else:
            # Fail LOUD, not hard: launch anyway but tell the caller the identity
            # couldn't be made consistent, so it doesn't ship a half-disguise
            # unknowingly. (A hard fail would wedge work for a geo nice-to-have.)
            identity_warning = (
                "proxy set but egress geo-lookup failed — timezone/geolocation "
                "left at host values, so the IP and location signals may be "
                "INCONSISTENT. Pass timezone=/geo= explicitly, verify the proxy, "
                "or set AI_DEV_BROWSER_GEO_ENDPOINT."
            )

    identity = build_identity(
        timezone=timezone, geo=parse_geo(geo), locale=locale, egress_ip=egress_ip
    )

    registry.register_instance(
        port=port,
        guid=ready_guid,
        workspace=os.getcwd(),
        pid=process.pid,
        user_data_dir=str(cdp_data_dir),
        identity=identity,
    )

    result = {
        "port": port,
        "pid": process.pid,
        "headless": headless_resolved,
        "url": start_url,
        "profile": profile_name,
        "automation_target_id": ready_target,
        "reused": False,
        "message": f"Browser started on port {port}",
    }
    # Surface the effective identity so the caller confirms consistency in one
    # call — no need to evaluate timezone/geo itself to verify.
    if identity_warning:
        result["identity_consistent"] = False
        result["identity_warning"] = identity_warning
    elif identity:
        result["identity_consistent"] = True
        if identity.get("timezone"):
            result["timezone"] = identity["timezone"]
        if identity.get("geo"):
            result["geolocation"] = identity["geo"]
        if identity.get("locale"):
            # Report the locale that actually LANDED (navigator.language), not the
            # request — Chrome maps --lang to its nearest supported UI locale, so
            # echoing the request would over-report (the v0.38.0 bug: it claimed
            # the locale applied while navigator.language was unchanged). Surface
            # the requested value too when Chrome normalized it away.
            requested = identity["locale"]
            effective = (
                _run_coro(_read_navigator_language(port, ready_target)) or requested
            )
            result["locale"] = effective
            if effective != requested:
                result["locale_requested"] = requested
        if egress_ip:
            result["egress_ip"] = egress_ip
    return _describe_cdp(result, start_options=start_options, guid=ready_guid)


async def _create_startup_page(port: int, guid: str, url: str, timeout: float) -> str:
    """Create the one startup target on the verified browser, without replay."""
    from ai_dev_browser.cdp import target
    from ._transport import CDPConnection

    connection = CDPConnection(f"ws://127.0.0.1:{port}/devtools/browser/{guid}")

    async def create():
        await connection.connect()
        return str(await connection.send(target.create_target(url), timeout=timeout))

    try:
        return await asyncio.wait_for(create(), timeout=timeout)
    finally:
        await connection.disconnect()


async def _prepare_startup_page(
    port: int, target_id: str, url: str, timeout: float
) -> None:
    """Prepare the blank owned page, then issue the requested navigation once.

    Chrome's temporary empty document can already report readyState=complete.
    Its navigation entry has no name and no DOMContentLoaded timestamp.
    """
    from ai_dev_browser.cdp import network, page, runtime
    from ._transport import CDPConnection, ProtocolException

    connection = CDPConnection(f"ws://127.0.0.1:{port}/devtools/page/{target_id}")

    async def wait_document(previous_loader=None):
        while True:
            try:
                frame = (await connection.send(page.get_frame_tree())).frame
                if previous_loader is not None and frame.loader_id == previous_loader:
                    await asyncio.sleep(0.01)
                    continue
                result, exception = await connection.send(
                    runtime.evaluate(
                        "performance.getEntriesByType('navigation').some("
                        "n => n.name && n.domContentLoadedEventEnd > 0)",
                        return_by_value=True,
                    )
                )
                if not exception and result.value is True:
                    return
            except ProtocolException as error:
                # The initial navigation can replace the temporary JS context.
                if "Execution context was destroyed" not in str(error):
                    raise
            await asyncio.sleep(0.01)

    async def prepare():
        await connection.connect()
        await connection.send(page.enable())
        # Commit the owned initial document before binding a CookieManager RPC
        # to its frame. The temporary frame can be replaced during startup.
        await wait_document()
        # A parsed blank page can precede Chrome's profile NetworkContext.
        # This origin-scoped CookieManager RPC waits for that context without
        # making an HTTP request. Discard its result; no cookies are modified.
        await connection.send(network.get_cookies(urls=[f"http://127.0.0.1:{port}/"]))
        if url != "about:blank":
            previous_loader = (
                await connection.send(page.get_frame_tree())
            ).frame.loader_id
            _, loader, error, *_ = await connection.send(page.navigate(url))
            if error:
                raise ProtocolException(
                    f"Navigation failed: {error}", method="Page.navigate"
                )
            await wait_document(previous_loader if loader else None)

    try:
        await asyncio.wait_for(prepare(), timeout=timeout)
    finally:
        await connection.disconnect()


def _query_initial_page(port: int) -> str | None:
    """A listening browser endpoint does not prove its initial page exists."""
    import json

    try:
        with _open_chrome_http(
            f"http://127.0.0.1:{port}/json/list", "127.0.0.1", 2
        ) as response:
            pages = [
                target for target in json.load(response) if target.get("type") == "page"
            ]
        return pages[0].get("id") if pages else None
    except (OSError, ValueError):
        return None


def _describe_cdp(
    result: dict, start_options: dict | None = None, guid: str | None = None
) -> dict:
    """Add observed process/session identity without changing legacy result fields."""
    port = result["port"]
    guid = guid or _query_chrome_guid(port)
    if not guid:
        return _session.failure(
            "transient",
            "Chrome debug port did not return a browser identity",
            **{**result, "transport": "cdp", "browser_closed": False},
        )
    identity = "cdp-" + guid
    try:
        record = _session.read(identity)
    except LookupError:
        record = {"session_id": identity, "transport": "cdp"}
    registered = registry.lookup(port, guid)
    observed = _session.process_info(result.get("pid") or get_pid_on_port(port)) or {}
    args = observed.get("launch_args", [])
    actual_headless = next(
        (a for a in reversed(args) if a == "--headless" or a.startswith("--headless=")),
        None,
    )
    headless = result.get("headless", record.get("headless"))
    if args:
        headless = (
            (headless if headless else actual_headless.partition("=")[2] or True)
            if actual_headless
            else False
        )
    record.update(
        {
            **observed,
            "port": port,
            "owner": "adb" if registered or start_options else "external",
            "profile_owner": "adb" if registered or start_options else "user",
            "user_data_dir": (registered or {}).get("user_data_dir"),
            "headless": headless,
        }
    )
    version = _query_chrome_version(port) or {}
    record["browser_version"] = version.get("Browser")
    record["profile_id"] = record.get("user_data_dir")
    if not record.get("automation_target_id"):
        record["automation_target_id"] = result.get(
            "automation_target_id"
        ) or _query_initial_page(port)
    if start_options:
        record["start_options"] = {
            **start_options,
            "chrome_path": start_options.get("chrome_path")
            or observed.get("chrome_path"),
        }
        record["workspace"] = os.getcwd()
    _session.write(record)
    return {**result, **_session.describe(record), "connected": True}


def _build_info() -> dict:
    """`{version}` (+ `git_commit` when running from a checkout) so a re-tester
    can tell WHICH code they're driving. In a repo-direct / editable run the
    packaged version is stale — setuptools-scm resolves it at build time, so the
    installed metadata lags the working tree — which makes the live git commit
    the unambiguous signal. Best-effort: omitted when there's no `.git` or git
    isn't callable."""
    from ai_dev_browser._version import __version__

    info: dict = {"version": __version__}
    try:
        import pathlib
        import subprocess

        root = pathlib.Path(__file__).resolve().parents[2]
        if (root / ".git").exists():
            r = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=2,
                **no_console_options(),
            )
            sha = r.stdout.strip()
            if r.returncode == 0 and sha:
                info["git_commit"] = sha
    except Exception:
        pass  # no git / not a checkout — version alone
    return info


@mode_guidance
async def browser_connect(
    transport: Literal["cdp", "extension"] = "cdp",
    port: int | None = None,
    session_id: str | None = None,
    headless: bool | str | None = None,
    timeout: float = 4.0,
) -> dict:
    """Use when: attaching to existing CDP or real Chrome; returns session identity and extension_warning to check before input.

    {mode_guidance}

    Connect never starts/restarts Chrome or changes its headless state. The
    extension gets a dedicated automation tab and follows its OAuth children;
    unrelated user tabs are excluded. profile_id identifies an extension
    installation in a profile even when account is absent. session_id identifies
    this authorization across worker/bridge reconnects. Explicit human recovery
    starts a new session in the same profile. Physical profile path and
    PID are unknown for a browser adb did not launch; unknown fields stay null.
    Use browser_list for OS inventory. A newly installed/reloaded extension
    may need a few seconds to dial the local bridge, which auto-starts.
    targets includes each page's index, target_id and URL. Use index for
    tab_switch/tab_close; automation_target_id tracks the main page identity.
    For visible local collaboration, show the dedicated page with tab_switch
    using its targets index so the human and agent work on that same page.
    Extension results report the loaded `extension_version` separately from
    `bundled_extension_version`; an unknown version stays null. Updating Python
    does not reload Chrome's extension. Ordinary extension reload can reset
    control: inspect the session and original owned page before further input.
    A non-null extension_warning means the runtime version is unknown or differs
    from the bundle: follow its update/reload steps before input. For extension,
    connected=true requires the dedicated page to exist. bridge_connected alone
    means the extension is reachable; page_available reports the dedicated page.
    Use window_set to verify actual foreground visibility.
    `bridge_runtime_version`, `bridge_version_matches_client` and
    `bridge_warning` describe the running Python daemon independently of the
    loaded extension. `bridge_driver_connections` is a pre-connect snapshot of
    controller sockets, including recorders, rather than a count of tasks.
    Unknown runtime fields stay null. Upgrading Python does not restart that
    daemon; use bridge_warning for coordinated recovery without closing Chrome.

    Args:
        transport: "cdp" (default, existing debug Chrome) or "extension"
            (running real Chrome with the bridge enabled in its profile).
        port: CDP debug port; auto-detected if omitted. Extension does not use it.
        session_id: Identity returned by start/connect; verifies that same
            browser/profile is still connected. Prefer browser_reconnect after
            a disconnect. Does not select a different profile.
        headless: An attached browser's mode cannot be changed. Any explicit
            value returns unsupported; select mode only in browser_start.
        timeout: Seconds to await an extension handshake, greater than zero.

    Returns:
        dict with connected, transport, session_id, capabilities, profile_id,
        bridge_connected and page_available for extension,
        owner, profile_owner, actual headless (null if unknown), account for
        extension, port for CDP, tabs and tab_count. Includes version/git_commit
        and loaded/bundled extension versions with their observed match status.
        extension_warning is null when versions match, otherwise actionable
        compatibility guidance; version matching alone does not prove visibility.

    Failure:
        Read error_code and setup_instructions. Missing bridge/extension needs
        the extension installed/enabled in the intended running Chrome profile.
        Reload the bundled bridge if its lifecycle identity is unavailable.
        A missing CDP Chrome needs an explicit start request or a corrected port.
        session_changed/target_closed require inspecting the actual state and an
        explicit decision; never restart, switch profile/transport or replay input.
        auth_failed with details.state=revoked reports stored debugger revocation;
        its reason/time may predate this request. Ask the human to click the
        AI Dev Browser extension toolbar action in that same Chrome profile
        (Extensions menu if unpinned), which authorizes a fresh visible blank
        page. Then browser_connect --transport extension returns a new session_id.
        This recovery requires the updated bundled extension; read extension_warning.
    """
    if headless is not None:
        return _session.failure(
            "unsupported",
            "Connect cannot change a running Chrome's headless state; choose it in browser_start",
            transport=transport,
        )
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    expected = _session.read(session_id) if session_id else None
    if expected and expected["transport"] != transport:
        return _session.failure(
            "validation",
            "session_id belongs to another transport; use browser_reconnect",
            session_id=session_id,
            transport=transport,
        )
    if transport == "extension":
        if port is not None:
            return _session.failure(
                "validation",
                "Extension connect does not use a CDP debug port",
                transport="extension",
            )
        if expected and expected.get("pid") and not _session.same_process(expected):
            return _session.failure(
                "session_changed",
                "Original extension Chrome process is gone; no browser was started or input replayed",
                session_id=session_id,
                transport="extension",
            )
        from .ext_bridge import bridge_status, ensure_bridge_running, wait_for_extension
        from .connection import connect_extension, _require_extension_page
        from .errors import SessionError

        connection_deadline = time.monotonic() + timeout
        if not ensure_bridge_running(timeout=timeout):
            return _session.failure(
                "transient",
                "The local extension bridge did not become ready within the connection timeout; Chrome was left running",
                transport="extension",
                extension_dir=str(extension_dir()),
            )
        status = await wait_for_extension(
            timeout=max(0.01, connection_deadline - time.monotonic())
        )
        if (
            status
            and not status.get("launch_token")
            and _session.pending_launch(EXTENSION_BRIDGE_PORT)
        ):
            while time.monotonic() < connection_deadline and not status.get(
                "launch_token"
            ):
                await asyncio.sleep(0.1)
                status = await bridge_status() or status
            if not status.get("launch_token"):
                return _session.failure(
                    "transient",
                    "The launched Chrome's worker connected before its profile launch identity was confirmed; inspect state and connect again without restarting",
                    transport="extension",
                    actual_profile_id=status.get("profile_id"),
                )
        if not status:
            return _session.failure(
                "transient",
                "No extension has connected in the requested time; check enabled bridge and running Chrome/profile",
                transport="extension",
                bridge_running=True,
                **bridge_version_info(await bridge_status(timeout=1) or {}),
                extension_dir=str(extension_dir()),
                setup_instructions=extension_load_instructions(),
                **_build_info(),
            )
        if not status.get("session_id") or not status.get("profile_id"):
            return _session.failure(
                "unsupported",
                "Connected bridge lacks lifecycle identity. Reload the updated bundled extension in the selected profile",
                transport="extension",
                bridge_running=True,
                **bridge_version_info(status),
                extension_dir=str(extension_dir()),
                setup_instructions=extension_load_instructions(),
            )
        identity = "extension-" + status["session_id"]
        if expected and (
            identity != session_id or status["profile_id"] != expected.get("profile_id")
        ):
            return _session.failure(
                "session_changed",
                "The connected Chrome/profile authorization differs from the requested session. No input was replayed",
                session_id=session_id,
                actual_session_id=identity,
                actual_profile_id=status["profile_id"],
                transport="extension",
            )
        try:
            record = _session.read(identity)
        except LookupError:
            record = _session.adopt_launch(status) or {
                "session_id": identity,
                "transport": "extension",
                "owner": "external",
                "profile_owner": "user",
            }
        main = status.get("automation_target_id")
        previous_main = record.get("automation_target_id")
        record.update(
            {
                "profile_id": status["profile_id"],
                "browser_version": status.get("browser_version"),
                **extension_version_info(status.get("extension_version")),
            }
        )
        record.setdefault("automation_target_id", main)
        _session.write(record)
        tabs = []
        browser = None
        try:
            browser = await connect_extension()
            # The low-level connection reads a fresh handshake. Its WebSocket
            # query binds the driver's lifetime to the session;
            # tab IDs alone cannot prove identity across profiles/authorizations.
            connected_session = parse_qs(
                urlsplit(browser.connection.websocket_url).query
            ).get("session", [None])[0]
            if connected_session != status["session_id"]:
                raise SessionError(
                    "Extension authorization changed during connection; inspect current state and connect explicitly",
                    "session_changed",
                )
            tabs = [
                {"tab_id": str(t._target.target_id), "url": t._target.url or ""}
                for t in browser.tabs
            ]
            loaded_version = await query_extension_version(
                browser, status.get("extension_version")
            )
            record.update(extension_version_info(loaded_version))
            await _require_extension_page(
                browser, expected.get("automation_target_id") if expected else main
            )
            if expected and expected.get("automation_target_id") != main:
                raise SessionError(
                    "Original automation page changed; inspect current state",
                    "target_closed",
                )
        except Exception as error:
            hint = getattr(error, "hint", None)
            return _session.failure(
                getattr(error, "error_code", "transient"),
                str(error),
                **_session.describe(record),
                bridge_connected=True,
                **bridge_version_info(status),
                page_available=False,
                tabs=[t["url"] for t in tabs],
                targets=[
                    {"index": i, "target_id": t["tab_id"], "url": t["url"]}
                    for i, t in enumerate(tabs)
                ],
                tab_count=len(tabs),
                details=getattr(error, "details", None),
                **({"hint": hint} if hint else {}),
                **_build_info(),
            )
        finally:
            if browser is not None:
                await browser.close()
        record.update(
            {
                "profile_id": status["profile_id"],
                "automation_target_id": main,
                "browser_version": status.get("browser_version"),
                **extension_version_info(loaded_version),
            }
        )
        _session.write(record)
        return {
            **_session.describe(record),
            "connected": True,
            **bridge_version_info(status),
            "bridge_connected": True,
            "page_available": True,
            "account": status.get("account"),
            "bridge_port": EXTENSION_BRIDGE_PORT,
            "tabs": [t["url"] for t in tabs],
            "targets": [
                {"index": i, "target_id": t["tab_id"], "url": t["url"]}
                for i, t in enumerate(tabs)
            ],
            "tab_count": len(tabs),
            "automation_tab_recreated": bool(previous_main and previous_main != main),
            **_build_info(),
        }
    if transport != "cdp":
        raise ValueError("transport must be cdp or extension")
    if expected:
        if port is not None and port != expected["port"]:
            return _session.failure(
                "validation",
                "port does not match session_id",
                session_id=session_id,
                transport="cdp",
            )
        port = expected["port"]
        observed_guid = _query_chrome_guid(port)
        if not observed_guid and (
            not expected.get("pid") or _session.same_process(expected)
        ):
            return _session.failure(
                "transient",
                "Original CDP browser identity is temporarily unavailable; no input was replayed",
                session_id=session_id,
                transport="cdp",
                port=port,
                pid=expected.get("pid"),
                browser_closed=False,
            )
        if "cdp-" + (observed_guid or "") != session_id:
            return _session.failure(
                "session_changed",
                "Original CDP Chrome is gone or this port now belongs to another browser; no input was replayed",
                session_id=session_id,
                transport="cdp",
                port=port,
            )
    try:
        browser = await connect_browser(port=port, session_id=session_id)
        try:
            tabs = [
                {"tab_id": str(t._target.target_id), "url": t._target.url or ""}
                for t in browser.tabs
            ]
            result = _describe_cdp({"port": browser.port})
        finally:
            await browser.close()
    except Exception as error:
        return _session.failure(
            getattr(error, "error_code", "transient"),
            str(error),
            transport="cdp",
            port=port,
        )
    if result.get("error"):
        return result
    record = _session.read(result["session_id"])
    if (
        expected
        and expected.get("automation_target_id")
        and expected["automation_target_id"] not in {t["tab_id"] for t in tabs}
    ):
        return _session.failure(
            "target_closed",
            "Original page target is closed; inspect the remaining tabs before continuing",
            session_id=session_id,
            transport="cdp",
            tabs=tabs,
        )
    if tabs and not record.get("automation_target_id"):
        record["automation_target_id"] = tabs[0]["tab_id"]
        _session.write(record)
    return {
        **result,
        **_session.describe(record),
        "tabs": [t["url"] for t in tabs],
        "targets": [
            {"index": i, "target_id": t["tab_id"], "url": t["url"]}
            for i, t in enumerate(tabs)
        ],
        "tab_count": len(tabs),
        **_build_info(),
    }


async def browser_reconnect(session_id: str, timeout: float = 10.0) -> dict:
    """Use when: control disconnected; reconnect session_id to the same Chrome/profile and return current tabs without replaying input.

    Does not start/restart a browser, change transport/profile, recreate a
    closed page state, or repeat a click/submission. The returned identity and
    tabs confirm reconnection; inspect page/server state before continuing an
    action whose previous result was uncertain.
    Read any extension_warning before input: a reconnected extension may still
    need an ordinary update/reload and another explicit connection.

    Args:
        session_id: Identity from browser_start/browser_connect.
        timeout: Seconds to wait for an extension handshake, greater than zero.

    Returns:
        dict with reconnected, connected, session_id, actual capabilities and tabs.

    Failure:
        session_changed means the browser, profile or authorization changed;
        target_closed means its original page is gone. Inspect actual state and
        request a new session explicitly. Missing extension needs the configured
        profile running and its bridge enabled. Do not replay input or restart.
        auth_failed with a revoked state needs the human to click the AI Dev
        Browser extension toolbar action in the same profile, then call
        browser_connect --transport extension for the fresh session_id.
        Stored revocation reason/time describe history, not necessarily this call.
    """
    record = _session.read(session_id)
    result = await browser_connect(
        transport=record["transport"],
        port=record.get("port"),
        session_id=session_id,
        timeout=timeout,
    )
    return {**result, "reconnected": result.get("connected", False)}


def browser_disconnect(session_id: str | None = None) -> dict:
    """Use when: releasing adb control while leaving Chrome and all page state running; returns disconnected and browser_closed=false.

    Extension disconnect stops its local bridge and drops driver connections;
    the dedicated tab and OAuth children stay in Chrome for browser_reconnect.
    It affects every adb driver of that one extension session, including active
    recordings. Disable the extension in chrome://extensions to revoke permission.
    CDP CLI connections are per-call; disconnect closes this process's cached
    connection. Future commands may reconnect; this is not browser_stop.

    Args:
        session_id: Scope to the identity returned by start/connect. Omitted
            preserves the existing extension bridge emergency-stop operation.

    Returns:
        dict with disconnected, stopped (legacy bridge field), was_running,
        browser_closed=false, session_id and affected_resources.

    Failure:
        A different active extension session is a conflict; do not disconnect
        another profile. Use the current session_id or inspect browser_connect.
    """
    from .ext_bridge import bridge_is_up, bridge_status, shutdown_bridge

    record = _session.read(session_id) if session_id else None
    if record and record["transport"] == "cdp":
        from .connection import BrowserClient

        browser = BrowserClient._instances.get(("127.0.0.1", record["port"]))
        if browser:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                return _session.failure(
                    "unsupported",
                    "An async Python caller must await browser.close() on its connection's event loop",
                    disconnected=False,
                    browser_closed=False,
                    session_id=session_id,
                )
            _run_coro(browser.close())
        return {
            "disconnected": True,
            "stopped": True,
            "was_running": bool(browser),
            "browser_closed": False,
            "session_id": session_id,
            "affected_resources": ["current process CDP connections"],
        }
    status = _run_coro(bridge_status())
    if (
        record
        and status
        and status.get("session_id")
        and "extension-" + status["session_id"] != session_id
    ):
        return _session.failure(
            "conflict",
            "Another extension session is active; its bridge was left untouched",
            disconnected=False,
            session_id=session_id,
        )
    was_running = bridge_is_up(EXTENSION_BRIDGE_PORT)
    if was_running:
        stopped = False
        if status and status.get("can_shutdown"):
            stopped = _run_coro(
                shutdown_bridge(
                    session_id=session_id.removeprefix("extension-")
                    if session_id
                    else None
                )
            )
        elif status:
            # Compatibility for an older adb daemon. Never kill an unrelated
            # listener or the host of an embedded bridge.
            pid = get_pid_on_port(EXTENSION_BRIDGE_PORT)
            observed = _session.process_info(pid)
            if (
                observed
                and "ai_dev_browser.core.ext_bridge" in observed.get("launch_args", [])
                and _session.same_process(observed)
            ):
                stopped = _kill_process_tree(pid)
        if not stopped:
            return _session.failure(
                "transient",
                "Could not release the selected extension bridge; unrelated processes were left untouched",
                disconnected=False,
                session_id=session_id,
            )
        deadline = time.monotonic() + 5
        while bridge_is_up(EXTENSION_BRIDGE_PORT) and time.monotonic() < deadline:
            time.sleep(0.05)
        if bridge_is_up(EXTENSION_BRIDGE_PORT):
            return _session.failure(
                "transient",
                "Bridge shutdown was requested but the listener has not closed; Chrome remains running",
                disconnected=False,
                browser_closed=False,
                session_id=session_id,
            )
    return {
        "disconnected": True,
        "stopped": True,
        "was_running": was_running,
        "browser_closed": False,
        "session_id": session_id,
        "affected_resources": [
            "all drivers and recordings on the local extension bridge"
        ],
    }


def browser_restart(session_id: str, allow_external: bool = False) -> dict:
    """Use when: explicitly restarting a known browser process; returns new session_id and the resources closed; reconnect uses browser_reconnect.

    Closes all windows/tabs of that process. Active recordings and pending
    actions end; no input is replayed. Named CDP profiles persist; disposable
    CDP profiles are recreated. Extension startup reuses its configured profile.
    External Chrome requires allow_external=True after the caller has obtained
    explicit authorization, plus verified PID/executable/start options. A real
    user's profile remains user-owned even when adb launched its Chrome.

    Args:
        session_id: Known session from browser_start/browser_connect.
        allow_external: Explicit authorization to restart an external process.
            Default False refuses it without closing any browser/tab.

    Returns:
        dict with restarted, previous_session_id, new session_id, capabilities
        and affected_resources (old PID, profile, all process windows/tabs).

    Failure:
        auth_failed needs explicit caller authorization for external Chrome.
        unsupported means executable/start settings are unknown: do not guess
        or copy the profile. session_changed means the original process ended.
        Inspect the returned state before making a separate start decision.
    """
    record = _session.read(session_id)
    if record.get("owner") != "adb" and not allow_external:
        return _session.failure(
            "auth_failed",
            "Explicit authorization is required to restart user-owned Chrome; no resources were closed",
            restarted=False,
            session_id=session_id,
            affected_resources=[],
        )
    options = record.get("start_options")
    if not options:
        return _session.failure(
            "unsupported",
            "Executable/start options of this attached Chrome are unknown; restart cannot be verified",
            restarted=False,
            session_id=session_id,
            affected_resources=[],
        )
    if not options.get("chrome_path") or not Path(options["chrome_path"]).is_file():
        return _session.failure(
            "unsupported",
            "The recorded launch executable is unavailable; no browser was closed. Restore that executable before restarting",
            restarted=False,
            session_id=session_id,
            browser_closed=False,
            affected_resources=[],
        )
    if options.get("profile") and record.get("workspace") != os.getcwd():
        return _session.failure(
            "conflict",
            "Named CDP profiles belong to their workspace; restart from the original workspace",
            restarted=False,
            session_id=session_id,
            workspace=record.get("workspace"),
            affected_resources=[],
        )
    if not _session.same_process(record):
        observed = _session.process_info(record.get("pid")) or {}
        return _session.failure(
            "session_changed",
            "Original Chrome process no longer matches its recorded PID/executable",
            restarted=False,
            session_id=session_id,
            expected_process={
                key: record.get(key)
                for key in ("pid", "process_created", "chrome_path")
            },
            actual_process={
                key: observed.get(key)
                for key in ("pid", "process_created", "chrome_path")
            },
            affected_resources=[],
        )
    affected = {
        "pid": record["pid"],
        "user_data_dir": record.get("user_data_dir"),
        "scope": "all windows/tabs and recordings in this browser process",
    }
    stopped = browser_stop(session_id=session_id, allow_external=allow_external)
    if stopped.get("error"):
        return {**stopped, "restarted": False}
    exit_deadline = time.monotonic() + 5
    while _session.same_process(record) and time.monotonic() < exit_deadline:
        time.sleep(0.1)
    if _session.same_process(record):
        return _session.failure(
            "transient",
            "The original process is still running; no replacement browser was launched",
            restarted=False,
            session_id=session_id,
            affected_resources=[affected],
        )
    try:
        result = browser_start(**options)
    except Exception as error:
        return _session.failure(
            "transient",
            f"Original browser closed, but replacement launch failed: {error}",
            restarted=False,
            previous_session_id=session_id,
            browser_closed=True,
            affected_resources=[affected],
        )
    return {
        **result,
        "restarted": bool(result.get("connected")),
        "previous_session_id": session_id,
        "affected_resources": [affected],
    }


def _graceful_stop(port: int, pid: int, timeout: float = 5.0) -> dict:
    """Gracefully stop a Chrome instance via CDP Browser.close().

    Sends Browser.close() which flushes cookies/profile data, then waits
    for the process to exit. Falls back to force-kill if graceful fails.

    Returns:
        dict with port, pid, and method used ("graceful" or "force").
    """
    process_identity = _session.process_info(pid)
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
            if not is_port_in_use(port=port) and (
                not process_identity or not _session.same_process(process_identity)
            ):
                _cleanup_temp_profile(port)
                registry.unregister_instance(port)
                return {"port": port, "pid": pid, "method": "graceful"}
            time.sleep(poll_interval)
            elapsed += poll_interval

    # Graceful failed or timed out — force kill
    if process_identity and _session.same_process(process_identity):
        _kill_process_tree(pid)
    _cleanup_temp_profile(port)
    registry.unregister_instance(port)
    return {"port": port, "pid": pid, "method": "force"}


def browser_stop(
    port: int | None = None,
    stop_all: bool = False,
    session_id: str | None = None,
    allow_external: bool = False,
) -> dict:
    """Use when: explicitly closing an adb-owned browser process; disconnect preserves Chrome, stop closes all its windows/tabs.

    Uses CDP Browser.close() for graceful shutdown (flushes cookies to
    profile SQLite). Falls back to force-kill if graceful fails.

    Args:
        port: Port of browser to stop
        stop_all: Stop all debugging Chrome instances adb launched. Registry-
            scoped — it only stops Chromes in adb's launch registry, so it can
            NEVER reap a debug Chrome adb didn't start (a user's own).
        session_id: Known CDP/extension session to close. Confirms the process
            still matches its recorded PID/executable. Extension closes every
            window of this process; its user-owned profile files are preserved.
        allow_external: Explicit caller authorization to close an external
            browser process. Default False protects attached user Chrome.

    Returns:
        dict with stopped status, count, browsers list

    Failure:
        auth_failed requires explicit caller authorization to close external
        Chrome. Unknown process ownership is unsupported. Use browser_disconnect
        to release control while preserving browser/page state. A changed session
        requires inspecting current state; never kill a recycled PID or port.
    """
    if session_id:
        if stop_all or port is not None:
            raise ValueError("Choose session_id or port/stop_all, not both")
        record = _session.read(session_id)
        if record.get("owner") != "adb" and not allow_external:
            return _session.failure(
                "auth_failed",
                "Explicit authorization required to close user Chrome",
                stopped=False,
                session_id=session_id,
            )
        if not record.get("pid") or not record.get("process_created"):
            return _session.failure(
                "unsupported",
                "This attached Chrome's physical process identity is unknown; use browser_disconnect to release control",
                stopped=False,
                session_id=session_id,
                affected_resources=[],
            )
        if not _session.same_process(record):
            return _session.failure(
                "session_changed",
                "Recorded Chrome process is gone or cannot be verified; no resources were closed",
                stopped=False,
                session_id=session_id,
                expected_process={
                    key: record.get(key)
                    for key in ("pid", "process_created", "chrome_path")
                },
                actual_process=_session.process_info(record.get("pid")),
                affected_resources=[],
            )
        if record["transport"] == "extension":
            from .connection import connect_extension
            from .cdp import cdp_send

            async def close_extension():
                browser = await connect_extension(session_id=session_id)
                try:
                    await cdp_send(
                        browser.tabs[0],
                        method="AiDevBrowser.closeBrowser",
                        params='{"authorized":true}',
                    )
                finally:
                    await browser.close()

            _run_coro(close_extension())
            deadline = time.monotonic() + 10
            while _session.same_process(record) and time.monotonic() < deadline:
                time.sleep(0.1)
            if _session.same_process(record):
                return _session.failure(
                    "transient",
                    "Chrome still has background resources after closing its windows; process was not force-killed",
                    stopped=False,
                    session_id=session_id,
                    pid=record["pid"],
                )
            return {
                "stopped": True,
                "count": 1,
                "session_id": session_id,
                "browsers": [
                    {
                        "pid": record["pid"],
                        "method": "extension-windows-close",
                        "user_data_dir": record["user_data_dir"],
                    }
                ],
            }
        port = record["port"]
        if "cdp-" + (_query_chrome_guid(port) or "") != session_id:
            return _session.failure(
                "session_changed",
                "Debug port belongs to another Chrome; nothing closed",
                stopped=False,
                session_id=session_id,
            )
    if not port and not stop_all:
        return {"error": "Please specify port or stop_all"}

    stopped = []

    if stop_all:
        # Registry-scoped: only Chromes adb launched. A debug Chrome adb didn't
        # start (rare — a user running --remote-debugging-port) has no registry
        # record and is left alone, so a blanket stop can't surprise-kill it.
        mine = registry.registered_ports()
        for p, pid, _ws in find_debug_chromes():
            if pid is None or p not in mine:
                continue
            try:
                result = _graceful_stop(p, pid)
                stopped.append(result)
            except Exception:
                pass
    else:
        owned = registry.lookup(port, _query_chrome_guid(port))
        if not owned and not allow_external:
            return _session.failure(
                "auth_failed",
                "Debug Chrome was not launched by adb; allow_external requires explicit caller authorization",
                stopped=False,
                port=port,
            )
        pid = get_pid_on_port(port)
        if pid is None and session_id:
            # Minimal containers may not have lsof. The session's PID/start time
            # and live Chrome GUID were verified above, so ownership is known.
            pid = record["pid"]
        if pid:
            result = _graceful_stop(port, pid)
            stopped.append(result)

    return {
        "stopped": True,
        "count": len(stopped),
        "browsers": stopped,
    }


def browser_list(all_workspaces: bool = False) -> dict:
    """Use when: you need to know WHICH Chromes are running and which are adb's
    vs the user's REAL browser — before connecting, or before any cleanup.
    Returns `{browsers, count, by_origin}`; each browser carries `origin`
    (`adb` = a live debug Chrome adb launched / `adb-orphan` = an adb-managed
    leftover with no live debug owner / `external` = the user's OWN Chrome),
    plus `pid`, `port` (debug port, null if none), `user_data_dir`, `profile`,
    `workspace`. `external` is never a cleanup target — reap only adb's leftovers
    with `browser_cleanup`.

    With the `cleanup` extra (psutil) this sees EVERY Chrome — including the
    user's real, non-debug browser — and classifies each **deterministically**
    (managed user-data-dir + live debug port), not by guessing from window
    titles. Without psutil it degrades to adb's debug Chromes only and says how
    to unlock the full view.

    Args:
        all_workspaces: Also include adb Chromes from OTHER workspaces (default:
            current workspace only). The user's `external` Chromes are always
            shown — they aren't workspace-scoped.

    Returns:
        dict with `browsers` (list), `count`, and — full view — `by_origin`
        counts + `psutil: true`. Without psutil: `psutil: false` + a `hint` to
        install the extra (and no `external` visibility).

    Failure:
        An empty list means no matching CDP browsers were found. Extension
        sessions are discovered by browser_connect --transport extension. Check
        the selected workspace/port before starting a new browser.
    """
    try:
        from .cleanup import list_chromes

        browsers = list_chromes(all_workspaces=all_workspaces)
    except ImportError:
        # No psutil → can't see the user's real (non-debug) Chrome. We can still
        # classify DEBUG Chromes deterministically from the launch registry:
        # `adb` (a port adb launched) vs `unknown` (a debug Chrome not in the
        # registry — could be external; without psutil we can't be sure). We
        # never label these `external` — that's reserved for the psutil path
        # that actually sees the user-data-dir.
        mine = registry.registered_ports()
        rows = (
            list(find_debug_chromes())
            if all_workspaces
            else [(p, pid, None) for p, pid in find_workspace_chromes()]
        )
        fallback: list[dict] = []
        for p, pid, workspace in rows:
            info: dict = {
                "port": p,
                "pid": pid,
                "origin": "adb" if p in mine else "unknown",
            }
            if workspace:
                info["workspace"] = workspace
            fallback.append(info)
        by_origin: dict[str, int] = {}
        for b in fallback:
            by_origin[b["origin"]] = by_origin.get(b["origin"], 0) + 1
        return {
            "browsers": fallback,
            "count": len(fallback),
            "by_origin": by_origin,
            "psutil": False,
            "hint": (
                "Install ai-dev-browser[cleanup] (psutil) to also see the user's "
                "real Chrome and classify external deterministically."
            ),
        }

    origin_counts: dict[str, int] = {}
    for b in browsers:
        origin_counts[b["origin"]] = origin_counts.get(b["origin"], 0) + 1
    return {
        "browsers": browsers,
        "count": len(browsers),
        "by_origin": origin_counts,
        "psutil": True,
    }
