"""Real HTTP results, fresh CLI processes and owned installed Chrome profiles."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid

import psutil
import pytest

from ai_dev_browser.core.extension import extension_dir


PAGE = """<!doctype html><meta charset=utf-8><title>Browser lifecycle acceptance</title>
<style>body{font:24px sans-serif;margin:50px;background:#eef2f7}button,input{font:inherit;padding:16px;margin:12px}</style>
<h1>Request approval</h1><button id=approve>Confirm as user</button>
<label>Request name <input id=name></label><button id=submit>Submit request</button>
<pre id=result>Loading</pre><script>
window.inputEvents=[];['mousedown','mouseup','click'].forEach(type=>document.addEventListener(type,e=>window.inputEvents.push({type,x:e.clientX,y:e.clientY,target:e.target.id,tag:e.target.tagName,trusted:e.isTrusted}),true));
async function state(){const s=await fetch('/status').then(r=>r.json());
document.querySelector('#result').textContent=JSON.stringify(s);
document.querySelector('#result').dataset.approved=String(s.approvals.length);
document.querySelector('#result').dataset.loggedIn=String(s.logged_in);window.serverState=s;return s}
document.querySelector('#approve').onclick=async e=>{await fetch('/approve',{method:'POST',body:JSON.stringify({trusted:e.isTrusted})});await state()};
document.querySelector('#submit').onclick=async e=>{await fetch('/submit',{method:'POST',body:JSON.stringify({trusted:e.isTrusted,name:document.querySelector('#name').value})});await state()};state();
</script>"""


class LifecycleServer:
    def __init__(self):
        self.login = uuid.uuid4().hex
        self.approvals = []
        self.submissions = []
        self.attempts = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *unused):
                pass

            def respond(
                self, body, content_type="application/json", cookie=False, status=200
            ):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                if cookie:
                    self.send_header(
                        "Set-Cookie",
                        f"adb_test_login={fixture.login}; Path=/; HttpOnly; Max-Age=3600; SameSite=Lax",
                    )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def authenticated(self):
                return f"adb_test_login={fixture.login}" in self.headers.get(
                    "Cookie", ""
                )

            def do_GET(self):
                if self.path in ("/", "/login"):
                    self.respond(
                        PAGE.encode(),
                        "text/html; charset=utf-8",
                        cookie=self.path == "/login",
                    )
                elif self.path == "/sentinel":
                    self.respond(
                        b"<title>Unrelated user tab</title><h1>Leave this tab untouched</h1>",
                        "text/html",
                    )
                elif self.path == "/status":
                    self.respond(
                        json.dumps(
                            {
                                "logged_in": self.authenticated(),
                                "approvals": fixture.approvals,
                                "submissions": fixture.submissions,
                            }
                        ).encode()
                    )
                elif self.path == "/popup":
                    self.respond(
                        (
                            PAGE
                            + '<button id="oauth">Open sign-in popup</button><script>document.querySelector("#oauth").onclick=()=>window.open("/oauth","_blank");window.addEventListener("message",e=>{if(e.origin===location.origin&&e.data==="approved")state()})</script>'
                        ).encode(),
                        "text/html; charset=utf-8",
                    )
                elif self.path == "/oauth":
                    self.respond(
                        b'<title>Sign-in approval</title><button id="consent">Approve sign-in</button><p id="done"></p><script>document.querySelector("#consent").onclick=async e=>{await fetch("/approve",{method:"POST",body:JSON.stringify({trusted:e.isTrusted})});document.querySelector("#done").textContent="Approved";window.opener.postMessage("approved",location.origin)}</script>',
                        "text/html",
                    )
                else:
                    self.respond(b"{}", status=404)

            def do_POST(self):
                data = json.loads(
                    self.rfile.read(int(self.headers.get("Content-Length", 0)))
                )
                fixture.attempts.append(
                    {
                        "path": self.path,
                        "authenticated": self.authenticated(),
                        "data": data,
                    }
                )
                if not self.authenticated():
                    self.respond(b'{"error":"login required"}', status=401)
                elif self.path == "/approve":
                    fixture.approvals.append(data)
                    self.respond(b'{"approved":true}')
                elif self.path == "/submit" and fixture.approvals:
                    fixture.submissions.append(data)
                    self.respond(b'{"submitted":true}')
                else:
                    self.respond(b'{"error":"approval required"}', status=409)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def wait(self, predicate):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        raise AssertionError(
            f"Server outcome missing: approvals={self.approvals}, submissions={self.submissions}"
        )


class LifecycleCLI:
    def __init__(self, root, **environment):
        self.root = Path(root)
        self.env = {
            k: v for k, v in os.environ.items() if not k.startswith("AI_DEV_BROWSER_")
        }
        for name in ("AI_DEV_BROWSER_CHROME", "AI_DEV_BROWSER_STARTUP_TIMEOUT"):
            if name in os.environ:
                self.env[name] = os.environ[name]
        self.env.update(environment)
        self.env.update(
            PYTHONUTF8="1", AI_DEV_BROWSER_RECORDING_DIR=str(self.root / "recordings")
        )
        self.history = []
        self.launches = []

    def __call__(self, tool, *flags, exit_code=0):
        run = subprocess.run(
            [sys.executable, "-m", f"ai_dev_browser.tools.{tool}", *map(str, flags)],
            capture_output=True,
            encoding="utf-8",
            env=self.env,
            timeout=120,
        )
        if "--help" in flags:
            assert run.returncode == exit_code, run.stderr
            return run.stdout
        assert run.stdout.strip(), (tool, run.returncode, run.stderr)
        result = json.loads(run.stdout)
        if (
            tool in ("browser_start", "browser_restart")
            and result.get("pid")
            and not result.get("reused")
        ):
            from ai_dev_browser.core import _session

            observed = _session.process_info(result["pid"])
            if observed:
                self.launches.append(observed)
        self.history.append(
            {
                "tool": tool,
                "flags": list(map(str, flags)),
                "exit_code": run.returncode,
                "result": result,
            }
        )
        print(f"LIVE {tool}: exit={run.returncode} {result}", flush=True)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "live-cli.json").write_text(
            json.dumps(self.history, indent=2), encoding="utf-8"
        )
        assert run.returncode == exit_code, (tool, flags, result, run.stderr)
        return result

    def evidence(self, name, **observations):
        path = self.root / f"{name}-evidence.json"
        path.write_text(
            json.dumps({"history": self.history, **observations}, indent=2),
            encoding="utf-8",
        )
        return path


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def owned_folder_picker(profile: Path, extension: Path):
    """Real Windows folder-picker UI, guarded by process/profile ownership."""
    import ctypes
    from ctypes import wintypes

    user = ctypes.windll.user32
    user.GetForegroundWindow.restype = wintypes.HWND
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.SetForegroundWindow.restype = wintypes.BOOL
    user.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetDlgCtrlID.argtypes = [wintypes.HWND]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user.SendMessageW.restype = wintypes.LPARAM
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        candidates = []

        @callback
        def visit(hwnd, unused):
            klass = ctypes.create_unicode_buffer(128)
            user.GetClassNameW(hwnd, klass, 128)
            title = ctypes.create_unicode_buffer(512)
            user.GetWindowTextW(hwnd, title, 512)
            if "extension" not in title.value.lower() and "扩展" not in title.value:
                return True
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                owner = psutil.Process(pid.value)
                wanted = os.path.normcase(str(profile.resolve()))
                if any(
                    wanted in os.path.normcase(arg.replace("/", "\\"))
                    for process in [owner, *owner.parents()]
                    for arg in process.cmdline()
                ):
                    candidates.append(hwnd)
            except psutil.Error:
                pass
            return True

        user.EnumWindows(visit, 0)
        for hwnd in candidates:
            buttons = []

            @callback
            def child(handle, unused):
                if user.GetDlgCtrlID(handle) == 1:
                    buttons.append(handle)
                return True

            user.EnumChildWindows(hwnd, child, 0)
            if not buttons:
                continue
            from pywinauto import Desktop

            dialog = Desktop(backend="uia").window(handle=hwnd)
            edit = dialog.child_window(
                auto_id="1152", control_type="Edit"
            ).wrapper_object()
            edit.set_edit_text(str(extension))
            assert edit.get_value() == str(extension)
            dialog.child_window(auto_id="1", control_type="Button").click()
            return
        time.sleep(0.1)
    raise AssertionError(
        "Owned extension folder picker was not found; no other profile/window was changed"
    )


def prepare_profile(root, binary, port, login_url=None):
    """Install with Chrome's own management UI, then prove persisted location=4."""
    if sys.platform != "win32":
        pytest.skip(
            "Persistent installed-profile bootstrap uses the actual Windows folder picker"
        )
    from playwright.sync_api import sync_playwright

    root = Path(root)
    profile = root / "profile"
    extension = root / "extension"
    shutil.copytree(extension_dir(), extension)
    source = extension / "background.js"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "127.0.0.1:9522", f"127.0.0.1:{port}"
        ),
        encoding="utf-8",
    )
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile),
            executable_path=binary,
            headless=False,
            ignore_default_args=["--disable-extensions"],
        )
        try:
            page = context.pages[0]
            page.goto("chrome://extensions")
            page.evaluate(
                "chrome.developerPrivate.updateProfileConfiguration({inDeveloperMode:true})"
            )
            selected = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "tests.integration.browser_lifecycle_ui",
                    "--profile",
                    str(profile),
                    "--extension",
                    str(extension),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            try:
                page.evaluate(
                    "window.adbInstalled=false;chrome.developerPrivate.loadUnpacked({},()=>window.adbInstalled=chrome.runtime.lastError?chrome.runtime.lastError.message:true)"
                )
                # A cold Windows UI Automation/COM import can consume much of
                # the folder picker's own 20s deadline before it starts.
                stdout, stderr = selected.communicate(timeout=60)
                assert selected.returncode == 0, (stdout, stderr)
                deadline = time.monotonic() + 10
                while (
                    page.evaluate("window.adbInstalled") is False
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.05)
            finally:
                if selected.poll() is None:
                    selected.terminate()
                    selected.communicate(timeout=5)
            assert page.evaluate("window.adbInstalled") is True, page.evaluate(
                "window.adbInstalled"
            )
            installed = page.evaluate(
                "new Promise(resolve=>chrome.developerPrivate.getExtensionsInfo({includeDisabled:true,includeTerminated:true},resolve))"
            )
            expected = [
                item
                for item in installed
                if os.path.normcase(item.get("path", ""))
                == os.path.normcase(str(extension))
            ]
            assert len(expected) == 1, [
                (e.get("name"), e.get("path")) for e in installed
            ]
            # Capture installation evidence in a dedicated tab, separated from
            # Chrome's initial extension bootstrap tab. The profile/extension
            # assertions still apply to the browser actually installed above.
            page = context.new_page()
            page.goto("chrome://extensions")
            page.screenshot(path=str(root / "installed-extension.png"))
            if login_url:
                page.goto(login_url)
                page.wait_for_function(
                    "window.serverState && window.serverState.logged_in"
                )
        finally:
            context.close()
    return profile, expected[0]["id"]
