"""Live Windows host click -> checked worker -> native Chrome foreground.

Run from the checkout root with a real Electron executable:
  python -m tests.integration.native_window_electron --electron PATH --output DIR

The temporary host is a real Electron window. Its button receives Windows mouse
input and starts the public helper directly. No browser, host authorization,
input lease, native activation or foreground observation is mocked. A consuming
application must additionally run its actual UI/model workflow.
"""

import argparse
import asyncio
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

import aiohttp
from aiohttp import web
import psutil

from ai_dev_browser.remote.native_window import (
    extension_process_id,
    helper_configuration,
)
from ai_dev_browser.core.extension import EXTENSION_BRIDGE_PORT
from ai_dev_browser.remote.worker import Worker, application


HOST = r"""
const {app,BrowserWindow,ipcMain}=require('electron');
const {spawn}=require('child_process');const fs=require('fs');
const config=JSON.parse(process.env.ADB_NATIVE_HOST_FIXTURE);
delete process.env.ADB_NATIVE_HOST_FIXTURE;
app.setPath('userData',config.userData);let window;
ipcMain.handle('show-owned-browser',()=>new Promise(resolve=>{
  window.setAlwaysOnTop(false);
  const child=spawn(config.python,['-I',config.helper],{
    windowsHide:true,stdio:['pipe','pipe','pipe']});
  let out='',err='';child.stdout.on('data',v=>out+=v);
  child.stderr.on('data',v=>err+=v);
  child.on('close',code=>{
    const result={code,out,err};fs.writeFileSync(config.result,JSON.stringify(result));
    resolve(result);
  });
  child.stdin.end(JSON.stringify({...config.request,parentPid:process.pid}));
}));
app.whenReady().then(async()=>{
  window=new BrowserWindow({width:700,height:420,show:false,alwaysOnTop:true,
    webPreferences:{nodeIntegration:true,contextIsolation:false}});
  await window.loadURL('data:text/html,'+encodeURIComponent(`
    <title>Owned browser window acceptance</title>
    <button style="margin:60px;width:300px;height:80px"
      onclick="require('electron').ipcRenderer.invoke('show-owned-browser')">
      Show owned Chrome
    </button>`));
  window.showInactive();
  const geometry=await window.webContents.executeJavaScript(`({
    width:innerWidth,height:innerHeight,
    button:document.querySelector('button').getBoundingClientRect().toJSON()})`);
  fs.writeFileSync(config.ready,JSON.stringify({pid:process.pid,
    hwnd:window.getNativeWindowHandle().readBigUInt64LE().toString(),geometry}));
});
app.on('window-all-closed',()=>app.quit());
"""


def reserve_port():
    with socket.socket() as item:
        item.bind(("127.0.0.1", 0))
        return item.getsockname()[1]


def click_owned_button(ready):
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    )
    user.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    user.WindowFromPoint.argtypes = (wintypes.POINT,)
    user.WindowFromPoint.restype = wintypes.HWND
    user.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user.GetAncestor.restype = wintypes.HWND
    user.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
    user.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    user.mouse_event.argtypes = (
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_size_t,
    )
    window = int(ready["hwnd"])
    owner, rect, origin = wintypes.DWORD(), wintypes.RECT(), wintypes.POINT()
    user.GetWindowThreadProcessId(window, ctypes.byref(owner))
    assert owner.value == ready["pid"]
    assert user.GetClientRect(window, ctypes.byref(rect))
    assert user.ClientToScreen(window, ctypes.byref(origin))
    geometry = ready["geometry"]
    button = geometry["button"]
    point = wintypes.POINT(
        round(
            origin.x
            + (button["x"] + button["width"] / 2) * rect.right / geometry["width"]
        ),
        round(
            origin.y
            + (button["y"] + button["height"] / 2) * rect.bottom / geometry["height"]
        ),
    )
    assert user.GetAncestor(user.WindowFromPoint(point), 2) == window, (
        "Owned fixture button is covered; no input sent"
    )
    previous = wintypes.POINT()
    assert user.GetCursorPos(ctypes.byref(previous))
    assert user.SetCursorPos(point.x, point.y)
    try:
        assert user.GetAncestor(user.WindowFromPoint(point), 2) == window
        user.mouse_event(0x0002, 0, 0, 0, 0)
        user.mouse_event(0x0004, 0, 0, 0, 0)
    finally:
        current = wintypes.POINT()
        if user.GetCursorPos(ctypes.byref(current)) and (current.x, current.y) == (
            point.x,
            point.y,
        ):
            user.SetCursorPos(previous.x, previous.y)


def foreground_pid():
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    )
    result = wintypes.DWORD()
    user.GetWindowThreadProcessId(user.GetForegroundWindow(), ctypes.byref(result))
    return result.value


async def main(args):
    assert sys.platform == "win32", "An interactive Windows desktop is required"
    assert args.electron.is_file()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    proof = {
        "passed": False,
        "actualWorker": True,
        "actualModel": False,
        "windowsMouse": False,
        "foregroundPolicyChanged": False,
        "sourceOverlay": False,
        "transport": "existing-extension" if args.existing_extension else "cdp",
    }
    worker = Worker(
        output / "profile",
        secrets.token_hex(32),
        secrets.token_hex(32),
        display_mode="native",
        chrome_path=str(args.chrome) if args.chrome else None,
        existing_extension_root=output / "personal-leases",
    )
    runner = web.AppRunner(application(worker))
    app = None
    app_endpoint = None
    chrome_pid = None
    try:
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        origin = "http://127.0.0.1:" + str(site._server.sockets[0].getsockname()[1])
        binding = {
            "orgId": "native-window-live",
            "userId": "fixture",
            "sessionId": secrets.token_hex(12),
        }
        worker.bind(binding)
        controller = "user-native-window-fixture"
        if args.existing_extension:
            selected = (
                await worker.invoke(controller, {"kind": "inspect-existing-extension"})
            )["existingExtension"]
            assert selected, "The fixture's existing Chrome extension is not connected"
            initial = (
                await worker.invoke(
                    controller, {"kind": "connect-existing-extension", **selected}
                )
            )["session"]
            chrome_pid = extension_process_id(EXTENSION_BRIDGE_PORT)
        else:
            initial = (
                await worker.invoke(
                    controller,
                    {"kind": "start", "isHeadless": False, "transport": "cdp"},
                )
            )["session"]
            chrome_pid = worker.browser["pid"]
        assert initial["state"] == "human" and initial["isController"]
        helper = helper_configuration()
        assert helper
        script = output / "host.cjs"
        script.write_text(HOST, encoding="utf-8")
        subprocess.run(
            [str(args.electron), "--version"],
            env={**os.environ, "ELECTRON_RUN_AS_NODE": "1"},
            capture_output=True,
            check=True,
            timeout=10,
        )
        config = {
            "python": helper["python"],
            "helper": helper["script"],
            "userData": str(output / "host-profile"),
            "ready": str(output / "host-ready.json"),
            "result": str(output / "activation.json"),
            "request": {
                "origin": origin,
                "token": worker.host_token,
                "binding": binding,
                "controller": controller,
                "action": {
                    "kind": "prepare-native-window",
                    "targetId": initial["activeTargetId"],
                    "controlEpoch": initial["controlEpoch"],
                    "targetEpoch": initial["targetEpoch"],
                },
            },
        }
        env = {**os.environ, "ADB_NATIVE_HOST_FIXTURE": json.dumps(config)}
        env.pop("ELECTRON_RUN_AS_NODE", None)
        app_port = reserve_port()
        with (output / "host.log").open("xb") as log:
            app = subprocess.Popen(
                [
                    str(args.electron),
                    str(script),
                    "--remote-debugging-port=" + str(app_port),
                ],
                env=env,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW
                | subprocess.NORMAL_PRIORITY_CLASS,
            )
        deadline = time.monotonic() + 25
        while not (output / "host-ready.json").exists():
            assert app.poll() is None, "The owned host exited before showing its button"
            assert time.monotonic() < deadline, "The owned host did not show its button"
            await asyncio.sleep(0.1)
        ready = json.loads((output / "host-ready.json").read_text(encoding="utf-8"))
        assert ready["pid"] == app.pid
        async with aiohttp.ClientSession() as http:
            async with http.get(
                f"http://127.0.0.1:{app_port}/json/version"
            ) as response:
                app_endpoint = (await response.json())["webSocketDebuggerUrl"]
        click_owned_button(ready)
        proof["windowsMouse"] = True
        deadline = time.monotonic() + 10
        while not (output / "activation.json").exists():
            assert time.monotonic() < deadline, "The native reveal did not complete"
            await asyncio.sleep(0.05)
        result = json.loads((output / "activation.json").read_text(encoding="utf-8"))
        assert result["code"] == 0, result
        reply = json.loads(result["out"])
        assert reply["nativeWindow"]["foreground"] is True
        assert foreground_pid() == chrome_pid
        after = (await worker.invoke(controller, {"kind": "state"}))["session"]
        for key in (
            "browserSessionId",
            "profileId",
            "activeTargetId",
            "controlEpoch",
            "targetEpoch",
            "state",
        ):
            assert after[key] == initial[key], key
        assert after["isController"] and after["isHumanControlHeld"]
        proof.update(
            passed=True,
            foregroundChromePid=chrome_pid,
            identityAndLeasePreserved=True,
            activation=reply["nativeWindow"],
        )
    finally:
        try:
            if app_endpoint:
                async with aiohttp.ClientSession() as http:
                    async with http.ws_connect(app_endpoint) as ws:
                        await ws.send_json({"id": 1, "method": "Browser.close"})
            if app:
                try:
                    await asyncio.to_thread(app.wait, 15)
                except subprocess.TimeoutExpired:
                    app.terminate()
                    await asyncio.to_thread(app.wait, 10)
                    proof["incompleteOwnedHostTerminated"] = True
        finally:
            await runner.cleanup()
            proof["ownedHostAndBrowserStopped"] = True
            if args.existing_extension and chrome_pid:
                proof["personalChromePreserved"] = psutil.pid_exists(chrome_pid)
                assert proof["personalChromePreserved"]
                proof["ownedHostAndBrowserStopped"] = False
                proof["ownedHostStoppedAndPersonalChromeDetached"] = True
            (output / "receipt.json").write_text(
                json.dumps(proof, indent=2), encoding="utf-8"
            )
            print(json.dumps(proof), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--electron", type=Path, required=True)
    parser.add_argument("--chrome", type=Path)
    parser.add_argument("--existing-extension", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
