"""Launch an already configured extension profile; never install or clone it."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import time
import uuid

from . import _session
from .chrome import find_chrome, _spawn_chrome
from .ext_bridge import bridge_status, ensure_bridge_running
from .extension import EXTENSION_BRIDGE_PORT, extension_dir, extension_load_instructions


def configured_extension(
    user_data_dir: Path, profile_directory: str, *, allow_disabled=False
) -> dict | None:
    """Read Chrome's installed-extension metadata, without rewriting preferences."""
    profile = user_data_dir / profile_directory
    for name in ("Preferences", "Secure Preferences"):
        try:
            preferences = json.loads((profile / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for identity, setting in (
            preferences.get("extensions", {}).get("settings", {}).items()
        ):
            path = setting.get("path")
            manifest = setting.get("manifest", {})
            if path and not manifest:
                try:
                    manifest = json.loads(
                        (Path(path) / "manifest.json").read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    continue
            if (
                manifest.get("name") == "AI Dev Browser — bridge"
                and (
                    allow_disabled
                    or (
                        setting.get("state", 1) == 1
                        and not setting.get("disable_reasons")
                    )
                )
                and setting.get("location") != 8  # Command-line loads are ephemeral.
            ):
                return {
                    "extension_id": identity,
                    "extension_path": path,
                    "extension_version": manifest.get("version"),
                }
    return None


async def start(
    *,
    user_data_dir,
    profile_directory,
    chrome_path,
    headless,
    url,
    startup_timeout,
    extra_args,
) -> dict:
    if not user_data_dir:
        return _session.failure(
            "validation",
            "Extension launch requires user_data_dir of an already configured Chrome profile",
            transport="extension",
        )
    root = Path(user_data_dir).expanduser().resolve()
    if Path(profile_directory).name != profile_directory or profile_directory in (
        ".",
        "..",
    ):
        return _session.failure(
            "validation",
            "profile_directory must be a single Chrome profile folder name",
            transport="extension",
        )
    binary = chrome_path or find_chrome()
    if not binary or not Path(binary).is_file():
        return _session.failure(
            "not_found",
            "Chrome executable not found; choose chrome_path or install Chrome",
            transport="extension",
        )
    if headless not in (False, True, "new", "old"):
        return _session.failure(
            "validation",
            "headless must be False, True, new, or old",
            transport="extension",
        )
    if headless == "old":
        return _session.failure(
            "unsupported",
            "Extension launch needs full Chrome architecture; legacy headless is unsupported. Choose new/True explicitly",
            transport="extension",
        )
    if (
        not headless
        and sys.platform.startswith("linux")
        and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    ):
        return _session.failure(
            "unsupported",
            "Windowed Chrome requires DISPLAY or WAYLAND_DISPLAY. Configure a GUI or explicitly choose headless",
            transport="extension",
        )
    arguments = list(extra_args or [])
    reserved = (
        "--remote-debugging",
        "--load-extension",
        "--disable-extensions",
        "--user-data-dir",
        "--profile-directory",
        "--headless",
    )
    if any(not arg.startswith("--") or arg.startswith(reserved) for arg in arguments):
        return _session.failure(
            "validation",
            "Extension extra_args cannot override profile/headless, install/disable extensions, add remote debugging, or supply URLs",
            transport="extension",
        )
    running = _session.profile_processes(root)
    if running:
        return _session.failure(
            "conflict",
            "Requested user-data-dir is already running; use browser_connect --transport extension. No process was closed or relaunched",
            transport="extension",
            running_pids=[p["pid"] for p in running],
            user_data_dir=str(root),
        )
    installed = configured_extension(root, profile_directory)
    if not installed:
        return _session.failure(
            "unsupported",
            "Bridge extension is not installed and enabled in the selected Chrome profile",
            transport="extension",
            user_data_dir=str(root),
            profile_directory=profile_directory,
            extension_dir=str(extension_dir()),
            setup_instructions=extension_load_instructions(),
        )
    if not ensure_bridge_running():
        return _session.failure(
            "unsupported",
            "Local extension bridge could not start",
            transport="extension",
        )
    active = await bridge_status()
    if active and active.get("extension_connected"):
        return _session.failure(
            "conflict",
            "Another extension session is connected. Disconnect it explicitly before launching another profile",
            transport="extension",
            active_profile_id=active.get("profile_id"),
        )
    token = uuid.uuid4().hex
    command = [
        str(Path(binary).resolve()),
        f"--user-data-dir={root}",
        f"--profile-directory={profile_directory}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if headless:
        command.append("--headless=new")
    command += arguments + [
        f"http://127.0.0.1:{EXTENSION_BRIDGE_PORT}/adb-launch/{token}"
    ]
    process = _spawn_chrome(command, silent_stderr=True)
    observed = _session.process_info(process.pid)
    record = {
        "transport": "extension",
        "bridge_port": EXTENSION_BRIDGE_PORT,
        "owner": "adb",
        "profile_owner": "user",
        **(observed or {}),
        "user_data_dir": str(root),
        "profile_directory": profile_directory,
        "headless": headless,
        "start_options": {
            "transport": "extension",
            "user_data_dir": str(root),
            "profile_directory": profile_directory,
            "chrome_path": command[0],
            "headless": headless,
            "startup_timeout": startup_timeout,
            "extra_args": arguments,
        },
    }
    if observed:
        _session.remember_launch(token, record)
    status = None
    deadline = time.monotonic() + startup_timeout
    while time.monotonic() < deadline:
        status = await bridge_status()
        if status and status.get("launch_token") == token:
            break
        if process.poll() is not None:
            break
        await asyncio.sleep(0.1)
    # Linux's google-chrome entry point is a shell wrapper that execs Chrome.
    # Sampling immediately after Popen can record /usr/bin/dash as the physical
    # executable. Refresh only the same process birth and exact launched root;
    # the nonce handshake still binds extension ownership to this launch.
    current = _session.process_info(process.pid)
    if (
        current
        and process.poll() is None
        and (
            not observed
            or current.get("process_created") == observed.get("process_created")
        )
        and f"--user-data-dir={root}" in current.get("launch_args", [])
        and not any(arg.startswith("--type=") for arg in current.get("launch_args", []))
    ):
        observed = current
        record.update(current)
        _session.remember_launch(token, record)
    if (
        not status
        or status.get("launch_token") != token
        or not status.get("session_id")
        or not status.get("profile_id")
    ):
        # The caller's real profile may have opened restore tabs. Keep it alive
        # and report its resources; a missing handshake never implies consent
        # to kill/restart it or to substitute another transport/profile.
        return _session.failure(
            "unsupported",
            "Chrome launched but the selected profile did not complete the expected extension handshake. Check extension/version/profile and reload the bridge; the launched browser was left running",
            transport="extension",
            pid=process.pid,
            launch_token=token,
            user_data_dir=str(root),
            profile_directory=profile_directory,
            headless=headless,
            started=process.poll() is None,
            owner="adb",
            profile_owner="user",
            browser_closed=False,
            affected_resources=[],
            extension_dir=str(extension_dir()),
            setup_instructions=extension_load_instructions(),
        )
    if not observed or process.poll() is not None:
        return _session.failure(
            "conflict",
            "The launched Chrome process exited or delegated to an existing browser; ownership could not be verified",
            transport="extension",
            pid=process.pid,
        )
    record.update(
        session_id="extension-" + status["session_id"],
        profile_id=status["profile_id"],
        browser_version=status.get("browser_version"),
        automation_target_id=status.get("automation_target_id"),
    )
    _session.adopt_launch(status)
    _session.write(record)
    from .browser import browser_connect

    result = await browser_connect(
        transport="extension", session_id=record["session_id"]
    )
    if result.get("connected") and (url or not headless):
        from .connection import connect_extension, get_active_tab
        from .navigation import page_goto
        from .cdp import cdp_send

        browser = await connect_extension(session_id=record["session_id"])
        try:
            tab = await get_active_tab(browser)
            if not headless:
                await cdp_send(
                    tab,
                    method="Target.activateTarget",
                    params=json.dumps({"targetId": result["automation_target_id"]}),
                )
            if url:
                navigation = await page_goto(tab, url=url)
                result["navigation"] = navigation
                result["url"] = navigation.get("url")
        finally:
            await browser.close()
    return {
        **_session.describe(record),
        **result,
        "started": process.poll() is None,
        "reused": False,
        **installed,
    }
