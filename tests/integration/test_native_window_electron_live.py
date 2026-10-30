"""Actual installed bridge protocol -> Windows button -> personal Chrome.

The shared fixture owns a disposable Chrome/profile; no user's profile is used.
Set AI_DEV_BROWSER_TEST_ELECTRON and AI_DEV_BROWSER_TEST_EXTENSION_CHROME.
The subprocess observes the configured bridge as an existing personal browser.
"""

import asyncio
import json
import os
from pathlib import Path
import sys

import psutil
import pytest


async def test_managed_cdp_native_window(tmp_path):
    electron = os.environ.get("AI_DEV_BROWSER_TEST_ELECTRON")
    chrome = os.environ.get("AI_DEV_BROWSER_CHROME")
    if sys.platform != "win32" or not electron or not chrome:
        pytest.skip("An interactive Windows desktop, Electron and Chrome are required")
    output = tmp_path / "native-host"
    with (tmp_path / "native-host-driver.log").open("wb") as log:
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tests.integration.native_window_electron",
            "--electron",
            electron,
            "--chrome",
            chrome,
            "--output",
            str(output),
            stdout=log,
            stderr=log,
        )
        try:
            code = await asyncio.wait_for(child.wait(), 90)
        finally:
            if child.returncode is None:
                child.terminate()
                await child.wait()
    proof = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
    assert code == 0, proof
    assert proof["passed"] and proof["windowsMouse"]
    assert proof["identityAndLeasePreserved"]
    assert proof["ownedHostAndBrowserStopped"]


@pytest.mark.extension_native
async def test_personal_extension_native_window(live_extension, tmp_path):
    electron = os.environ.get("AI_DEV_BROWSER_TEST_ELECTRON")
    if sys.platform != "win32" or not electron:
        pytest.skip("An interactive Windows desktop and Electron fixture are required")
    assert Path(electron).is_file()
    output = tmp_path / "native-host"
    env = {
        **os.environ,
        "AI_DEV_BROWSER_EXTENSION_BRIDGE_PORT": str(live_extension.port),
    }
    with (tmp_path / "native-host-driver.log").open("wb") as log:
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tests.integration.native_window_electron",
            "--electron",
            electron,
            "--existing-extension",
            "--output",
            str(output),
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            code = await asyncio.wait_for(child.wait(), 90)
        finally:
            if child.returncode is None:
                child.terminate()
                await child.wait()
    proof = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
    assert code == 0, proof
    assert proof["passed"] and proof["windowsMouse"]
    assert proof["foregroundChromePid"] == live_extension.chrome_pid
    assert proof["identityAndLeasePreserved"]
    assert proof["personalChromePreserved"]
    assert psutil.pid_exists(live_extension.chrome_pid)
