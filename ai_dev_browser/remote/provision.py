"""Prepare an explicitly managed profile using Chrome's installation policy.

Administrators provision the machine policy and signed extension update server.
This helper never installs an unpacked extension, rewrites extension metadata,
or changes an existing running browser. Ordinary extension connection does not
invoke it. It is intended for a host-owned, initially empty cloud profile.
"""

import asyncio
import re
import time
from pathlib import Path

from ..cdp import runtime
from ..core._extension_lifecycle import configured_extension
from ..core.browser import browser_start, browser_stop
from ..core.connection import connect_browser, get_active_tab
from ..core.ext_bridge import bridge_status, ensure_bridge_running
from ..core.navigation import page_goto
from .control import ControlError


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+){0,3}", value):
        return None
    return tuple(int(part) for part in value.split(".")) + (0,) * (
        4 - len(value.split("."))
    )


async def prepare_managed_extension_profile(
    user_data_dir: str,
    *,
    extension_id: str,
    minimum_version: str | None = None,
    chrome_path: str | None = None,
    timeout: float = 45,
    extra_args: list[str] | None = None,
):
    root = Path(user_data_dir).resolve()
    installed = configured_extension(root, "Default", allow_disabled=True)
    required = _version(minimum_version) if minimum_version is not None else None
    if minimum_version is not None and required is None:
        raise ValueError("Invalid minimum extension version")

    def compatible(value):
        current = _version(value)
        return required is None or (current is not None and current >= required)

    if installed:
        if installed["extension_id"] != extension_id:
            raise ControlError("managed_extension_identity_changed")
        if compatible(installed.get("extension_version")) and configured_extension(
            root, "Default"
        ):
            return
    if not installed and (root / "Default").exists():
        raise ControlError("existing_profile_requires_extension_setup")
    if not await asyncio.to_thread(ensure_bridge_running):
        raise ControlError("extension_bridge_unavailable")
    status = await bridge_status()
    if status and status.get("extension_connected"):
        raise ControlError("another_extension_profile_connected")
    browser = await asyncio.to_thread(
        browser_start,
        profile=str(root),
        headless=True,
        chrome_path=chrome_path,
        override_default_args={
            "--disable-extensions": None,
            "--disable-background-networking": None,
        },
        extra_args=extra_args,
        stealth=False,
        # Bootstrap is short lived; retain exit-time diagnostics for an update
        # failure. Long-running host-owned Chrome keeps its own logging policy.
        silent_stderr=False,
    )
    if "error" in browser:
        raise ControlError(
            "managed_profile_bootstrap_failed",
            details={
                key: browser.get(key)
                for key in ("error", "error_code", "pid", "port", "started", "reused")
            },
        )
    try:
        if installed:
            # Use Chrome's own Update action for the host-owned profile. Its
            # background update schedule is insufficient for a bounded upgrade.
            # Chromium extensions/service.ts uses this same native API.
            client = await connect_browser(session_id=browser["session_id"])
            try:
                tab = await get_active_tab(client)
                await page_goto(tab, "chrome://extensions/")
                result, exception = await tab.send(
                    runtime.evaluate(
                        "chrome.developerPrivate.autoUpdate().then(()=>true)",
                        await_promise=True,
                        return_by_value=True,
                    )
                )
                if exception or result.value is not True:
                    raise ControlError("managed_extension_update_request_failed")
            finally:
                await client.close()
        deadline = time.monotonic() + timeout
        while True:
            status = await bridge_status()
            if (
                status
                and status.get("extension_connected")
                and compatible(status.get("extension_version"))
            ):
                break
            if time.monotonic() >= deadline:
                raise ControlError(
                    "managed_extension_update_timeout"
                    if installed
                    else "managed_extension_install_timeout"
                )
            await asyncio.sleep(0.1)
    finally:
        stopped = await asyncio.to_thread(
            browser_stop, session_id=browser["session_id"]
        )
        if not stopped.get("stopped"):
            raise ControlError("managed_profile_bootstrap_not_stopped")
    installed = configured_extension(root, "Default")
    if (
        not installed
        or installed["extension_id"] != extension_id
        or not compatible(installed.get("extension_version"))
    ):
        raise ControlError("managed_extension_install_not_verified")
