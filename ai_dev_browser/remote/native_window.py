"""Reveal an owned Windows Chrome window after an explicit host UI action.

The foreground application starts the actual interpreter directly, with this
file as its script. A venv redirector can introduce an extra process and lose
Windows' foreground eligibility. Authentication travels only through stdin.
This helper never changes foreground policy or synthesizes focus shortcuts.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
import urllib.error
import urllib.request


class NativeWindowError(RuntimeError):
    def __init__(self, code, details=None):
        super().__init__(code)
        self.details = details


def helper_configuration():
    if sys.platform != "win32":
        return None
    return {
        "python": str(Path(sys._base_executable).resolve()),
        "script": str(Path(__file__).resolve()),
    }


def extension_process_id(port):
    """Resolve the one local Chrome connected to this selected bridge.

    This works for personal Chrome without launch records or new extension
    permissions. The caller checks the bridge's run/profile identity on both
    sides of this lookup. No other connection or process metadata is returned.
    """
    import psutil

    if sys.platform != "win32" or type(port) is not int or not 1 <= port <= 65535:
        raise NativeWindowError("native_window_process_unavailable")
    roots = set()
    try:
        for connection in psutil.net_connections(kind="tcp"):
            if (
                connection.status != psutil.CONN_ESTABLISHED
                or not connection.pid
                or not connection.raddr
                or connection.raddr.port != port
                or connection.raddr.ip not in ("127.0.0.1", "::1")
                or connection.laddr.ip not in ("127.0.0.1", "::1")
            ):
                continue
            try:
                process = psutil.Process(connection.pid)
                for _ in range(8):
                    if Path(process.exe()).name.lower() != "chrome.exe":
                        break
                    if not any(arg.startswith("--type=") for arg in process.cmdline()):
                        roots.add(process.pid)
                        break
                    process = process.parent()
                    if process is None:
                        break
            except psutil.NoSuchProcess:
                # A closed socket cannot establish the selected browser owner.
                continue
    except psutil.AccessDenied:
        raise NativeWindowError(
            "native_window_process_unavailable", {"reason": "AccessDenied"}
        ) from None
    if len(roots) != 1:
        raise NativeWindowError("native_window_process_ambiguous")
    return roots.pop()


def process_identity(pid):
    if sys.platform != "win32" or type(pid) is not int or pid <= 0:
        raise NativeWindowError("native_window_process_invalid")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        *([ctypes.POINTER(wintypes.FILETIME)] * 4),
    )
    kernel.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise NativeWindowError("native_window_process_unavailable")
    try:
        created, exited, system, user = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(
            handle, *(ctypes.byref(v) for v in (created, exited, system, user))
        ):
            raise NativeWindowError("native_window_process_unavailable")
        size = wintypes.DWORD(32768)
        executable = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(
            handle, 0, executable, ctypes.byref(size)
        ):
            raise NativeWindowError("native_window_process_unavailable")
        if Path(executable.value).name.lower() != "chrome.exe":
            raise NativeWindowError("native_window_process_invalid")
        return {
            "pid": pid,
            "created": (created.dwHighDateTime << 32) | created.dwLowDateTime,
            "executable": str(Path(executable.value).resolve()),
        }
    finally:
        kernel.CloseHandle(handle)


def activate_window(descriptor, parent_pid):
    """Use one normal Windows activation request; preserve newer foreground work."""
    if sys.platform != "win32" or type(parent_pid) is not int or parent_pid <= 0:
        raise NativeWindowError("native_window_host_invalid")
    if os.getppid() != parent_pid:
        raise NativeWindowError("native_window_host_changed")
    identity = descriptor.get("process")
    title = descriptor.get("title")
    if (
        not isinstance(identity, dict)
        or not isinstance(title, str)
        or len(title) > 4096
    ):
        raise NativeWindowError("native_window_descriptor_invalid")
    if process_identity(identity.get("pid")) != identity:
        raise NativeWindowError("native_window_process_changed")
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    )
    user.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user.IsWindowVisible.argtypes = (wintypes.HWND,)
    user.IsIconic.argtypes = (wintypes.HWND,)
    user.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user.SetForegroundWindow.argtypes = (wintypes.HWND,)
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = (callback, wintypes.LPARAM)

    def owner(window):
        result = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(result))
        return result.value

    candidates = []

    @callback
    def inspect(window, _unused):
        if owner(window) != identity["pid"] or not user.IsWindowVisible(window):
            return True
        label, kind = (
            ctypes.create_unicode_buffer(8192),
            ctypes.create_unicode_buffer(256),
        )
        user.GetWindowTextW(window, label, len(label))
        user.GetClassNameW(window, kind, len(kind))
        if kind.value == "Chrome_WidgetWin_1" and (
            not title or label.value == title or label.value.startswith(title + " - ")
        ):
            candidates.append(window)
        return True

    user.EnumWindows(inspect, 0)
    if len(candidates) != 1:
        raise NativeWindowError("native_window_target_ambiguous")
    window = candidates[0]
    foreground = user.GetForegroundWindow()
    if foreground == window:
        return {"foreground": True, "alreadyVisible": True}
    if owner(foreground) != parent_pid:
        raise NativeWindowError("native_window_foreground_changed")
    if process_identity(identity["pid"]) != identity:
        raise NativeWindowError("native_window_process_changed")
    if user.IsIconic(window):
        user.ShowWindow(window, 9)
    # No retry, Alt input, thread attachment, focus emulation or policy change.
    accepted = bool(user.SetForegroundWindow(window))
    deadline = time.monotonic() + 1
    while user.GetForegroundWindow() != window and time.monotonic() < deadline:
        time.sleep(0.02)
    if not accepted or user.GetForegroundWindow() != window:
        raise NativeWindowError("native_window_activation_unavailable")
    return {"foreground": True, "alreadyVisible": False}


def run(payload):
    if set(payload) != {
        "origin",
        "token",
        "binding",
        "controller",
        "action",
        "parentPid",
    }:
        raise NativeWindowError("native_window_request_invalid")
    origin = urlsplit(payload["origin"])
    if (
        origin.scheme != "http"
        or origin.hostname != "127.0.0.1"
        or not origin.port
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise NativeWindowError("native_window_endpoint_invalid")
    action = payload["action"]
    if not isinstance(action, dict) or action.get("kind") != "prepare-native-window":
        raise NativeWindowError("native_window_request_invalid")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, _req, _fp, _code, _msg, _headers, _url):
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(
        payload["origin"] + "/invoke",
        data=json.dumps(
            {key: payload[key] for key in ("binding", "controller", "action")}
        ).encode(),
        headers={
            "Authorization": "Bearer " + payload["token"],
            "Content-Type": "application/json",
        },
    )
    try:
        with opener.open(request, timeout=5) as response:
            reply = json.loads(response.read(1024 * 1024))
    except urllib.error.HTTPError as error:
        raw = (
            error.read(4096)
            .decode(errors="replace")
            .replace(payload["token"], "[redacted]")
        )
        raise NativeWindowError(
            "native_window_worker_refused_" + str(error.code),
            {"status": error.code, "response": raw},
        ) from None
    descriptor = reply.pop("nativeWindow")
    reply["nativeWindow"] = activate_window(descriptor, payload["parentPid"])
    return reply


def main():
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise NativeWindowError("native_window_request_invalid")
        value = run(json.loads(raw))
        print(json.dumps(value), flush=True)
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, NativeWindowError)
            else "native_window_failed"
        )
        result = {"error": code}
        if isinstance(error, NativeWindowError) and error.details is not None:
            result["details"] = error.details
        print(json.dumps(result), flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
