"""Owned, loopback-only x11vnc/websockify lifecycle for an existing X display."""

import socket
import subprocess
import time
from pathlib import Path


class VncView:
    """Expose an isolated display to an authenticated host's noVNC tunnel.

    The caller supplies a private VNC password file, an isolated X display,
    noVNC system assets and ports. This class does not create a display, launch
    Chrome, publish a public listener, authenticate HTTP users or erase files.
    """

    def __init__(
        self,
        *,
        display,
        password_file,
        vnc_port=5907,
        web_port=6087,
        web_root="/usr/share/novnc",
        timeout=10,
        view_only=False,
    ):
        if not display or vnc_port == web_port:
            raise ValueError("An isolated display and distinct ports are required")
        for port in (vnc_port, web_port):
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("Invalid viewer port")
        if not Path(password_file).is_file() or not Path(web_root).is_dir():
            raise ValueError("Viewer password file and noVNC assets are required")
        self.display, self.password_file = display, str(password_file)
        self.vnc_port, self.web_port = vnc_port, web_port
        self.web_root, self.timeout = str(web_root), timeout
        if type(view_only) is not bool:
            raise ValueError("An explicit boolean viewer input policy is required")
        self.view_only = view_only
        self.processes = []

    def _wait(self, port):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if not self.running:
                raise RuntimeError("Viewer process stopped during startup")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.05)
        raise TimeoutError("Viewer listener did not start")

    @property
    def running(self):
        return bool(self.processes) and all(p.poll() is None for p in self.processes)

    def start(self):
        if self.processes:
            raise RuntimeError("This viewer has already been started")
        # Fail before spawning if a different session already owns either port.
        for port in (self.vnc_port, self.web_port):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
        try:
            self.processes.append(
                subprocess.Popen(
                    [
                        "x11vnc",
                        "-display",
                        self.display,
                        "-localhost",
                        "-rfbport",
                        str(self.vnc_port),
                        "-passwdfile",
                        self.password_file,
                        "-forever",
                        "-shared",
                        "-noxdamage",
                        # Enforce this at the X server adapter. A client can
                        # change noVNC's viewOnly setting or send raw RFB input.
                        *(["-viewonly", "-nosel"] if self.view_only else []),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            self._wait(self.vnc_port)
            self.processes.append(
                subprocess.Popen(
                    [
                        "websockify",
                        "--web=" + self.web_root,
                        "127.0.0.1:" + str(self.web_port),
                        "127.0.0.1:" + str(self.vnc_port),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
            self._wait(self.web_port)
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        for process in reversed(self.processes):
            if process.poll() is not None:
                continue
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()
