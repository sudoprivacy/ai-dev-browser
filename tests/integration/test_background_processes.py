"""Real subprocess/Windows-console regressions; no mocked spawn flags."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

from ai_dev_browser.core.ext_bridge import ensure_bridge_running, shutdown_bridge
from ai_dev_browser.core.process import get_pid_on_port, no_console_options


ROOT = Path(__file__).resolve().parents[2]


def test_detached_venv_worker_survives_caller_without_console(tmp_path):
    evidence = tmp_path / "detached-worker.json"
    worker = "\n".join(
        [
            "import ctypes,json,os,pathlib,time",
            "time.sleep(0.3)",
            "console = int(ctypes.windll.kernel32.GetConsoleWindow()) if os.name == 'nt' else None",
            f"pathlib.Path({str(evidence)!r}).write_text(json.dumps(dict(pid=os.getpid(),console=console)),encoding='utf-8')",
        ]
    )
    producer = "\n".join(
        [
            "import importlib.util,subprocess,sys",
            f"spec=importlib.util.spec_from_file_location('process_helpers',{str(ROOT / 'ai_dev_browser/core/process.py')!r})",
            "helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)",
            f"subprocess.Popen([sys.executable,'-c',{worker!r}],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**helpers.detached_process_options())",
        ]
    )
    subprocess.run(
        [sys.executable, "-c", producer],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        timeout=10,
        **no_console_options(),
    )
    deadline = time.monotonic() + 10
    while not evidence.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert evidence.exists(), "worker did not survive its caller"
    result = json.loads(evidence.read_text(encoding="utf-8"))
    if os.name == "nt":
        assert result["console"] == 0, result


@pytest.mark.skipif(os.name != "nt", reason="Windows background GUI-to-console launch")
def test_background_gui_console_child_has_no_window(tmp_path):
    evidence = tmp_path / "background-command-evidence.json"
    worker = "\n".join(
        [
            "import ctypes,json,pathlib",
            "kernel=ctypes.WinDLL('kernel32')",
            "kernel.GetConsoleWindow.restype=ctypes.c_void_p",
            f"pathlib.Path({str(evidence)!r}).write_text(json.dumps(dict(window=int(kernel.GetConsoleWindow() or 0))),encoding='utf-8')",
        ]
    )
    producer = "\n".join(
        [
            "import importlib.util,subprocess",
            f"spec=importlib.util.spec_from_file_location('process_helpers',{str(ROOT / 'ai_dev_browser/core/process.py')!r})",
            "helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)",
            f"subprocess.run([{sys.executable!r},'-c',{worker!r}],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,**helpers.no_console_options())",
        ]
    )
    subprocess.run(
        [str(Path(sys.executable).with_name("pythonw.exe")), "-c", producer],
        cwd=ROOT,
        check=True,
        timeout=15,
    )
    assert json.loads(evidence.read_text(encoding="utf-8"))["window"] == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows console allocation contract")
def test_real_extension_bridge_has_no_console_window_and_shuts_down(tmp_path):
    # Use the actual Windows venv launcher, the path that reproduced the popup.
    assert sys.prefix != sys.base_prefix, "run this regression in the CI venv"
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    try:
        # The new checkout's measured package cold import is ~13 s while other
        # builds/Defender are active. This is a bounded fixture startup budget,
        # not a change to the production default or console-free assertion.
        assert ensure_bridge_running(port, timeout=30)
        bridge_pid = get_pid_on_port(port)
        assert bridge_pid
        observer = "\n".join(
            [
                "import ctypes,json",
                "kernel=ctypes.WinDLL('kernel32',use_last_error=True)",
                "kernel.GetConsoleWindow.restype=ctypes.c_void_p",
                "kernel.FreeConsole()",
                f"attached=bool(kernel.AttachConsole({bridge_pid}))",
                "error=ctypes.get_last_error()",
                "window=int(kernel.GetConsoleWindow() or 0)",
                "if attached: kernel.FreeConsole()",
                "print(json.dumps(dict(attached=attached,error=error,window=window)))",
            ]
        )
        run = subprocess.run(
            [sys.executable, "-c", observer],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        console = json.loads(run.stdout)
        (tmp_path / "bridge-console-evidence.json").write_text(
            json.dumps({"bridge_pid": bridge_pid, **console}), encoding="utf-8"
        )
        # CREATE_NO_WINDOW may retain an invisible console object. The actual
        # user contract is no allocated console window, not AttachConsole's
        # success/error (which also depends on the observer's own attachment).
        assert console["window"] == 0, console
    finally:
        # Also runs when readiness fails, so a late worker is not abandoned.
        asyncio.run(shutdown_bridge(port))
        deadline = time.monotonic() + 5
        while get_pid_on_port(port) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert get_pid_on_port(port) is None
