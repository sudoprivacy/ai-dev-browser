"""Pixels and trusted input for a host-owned isolated X11 browser display."""

import asyncio
import base64
import io
import math
import os
import re
import shutil

from PIL import ImageGrab


class XDisplay:
    """Own a headful display and its window manager, with no public listener.

    Hosts create this only for headful Chrome and keep it until Chrome stops.
    It manages keyboard focus and native windows; viewers do not own its life.
    """

    def __init__(self, width=1280, height=900):
        if os.name != "posix" or any(
            not shutil.which(tool) for tool in ("Xvfb", "openbox", "xprop")
        ):
            raise ValueError("Headful display requires Xvfb, openbox and xprop")
        if not 320 <= width <= 8192 or not 240 <= height <= 8192:
            raise ValueError("Invalid display dimensions")
        self.width, self.height = width, height
        self.server = self.manager = None
        self.display = None

    async def start(self):
        if self.server:
            if self.server.returncode is not None:
                raise RuntimeError("Owned display disconnected")
            return self.display
        try:
            self.server = await asyncio.create_subprocess_exec(
                "Xvfb",
                "-displayfd",
                "1",
                "-screen",
                "0",
                f"{self.width}x{self.height}x24",
                "-nolisten",
                "tcp",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            number = (
                (await asyncio.wait_for(self.server.stdout.readline(), 10))
                .decode()
                .strip()
            )
            if not re.fullmatch(r"\d+", number):
                raise RuntimeError("Owned display did not start")
            self.display = ":" + number
            self.manager = await asyncio.create_subprocess_exec(
                "openbox",
                "--sm-disable",
                env={**os.environ, "DISPLAY": self.display},
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            deadline = asyncio.get_running_loop().time() + 10
            while self.manager.returncode is None:
                probe = await asyncio.create_subprocess_exec(
                    "xprop",
                    "-display",
                    self.display,
                    "-root",
                    "_NET_SUPPORTING_WM_CHECK",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    output, _ = await asyncio.wait_for(probe.communicate(), 2)
                finally:
                    if probe.returncode is None:
                        probe.kill()
                        await probe.wait()
                if b"window id #" in output:
                    return self.display
                if asyncio.get_running_loop().time() >= deadline:
                    break
                await asyncio.sleep(0.05)
            raise RuntimeError("Owned window manager did not start")
        except BaseException:
            await self.close()
            raise

    async def close(self):
        for process in (self.manager, self.server):
            if process and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        self.server = self.manager = self.display = None


class WindowView:
    """Share Chrome UI using the same frame/input surface as a page view.

    The host creates an isolated X display, authenticates callers and holds a
    browser control lease around every call. This adapter owns no Chrome,
    display server, profile or public port. It never captures the user's local
    desktop or automatically replays input.
    """

    def __init__(self, *, display, quality=65, max_text=512):
        if os.name != "posix" or not re.fullmatch(r":\d+(?:\.\d+)?", display or ""):
            raise ValueError("An isolated local X11 display is required")
        if not 0 <= quality <= 100 or max_text <= 0 or not shutil.which("xdotool"):
            raise ValueError("Window view requires valid limits and xdotool")
        self.display, self.quality, self.max_text = display, quality, max_text
        self.width = self.height = 0

    async def capture(self):
        def grab():
            image = ImageGrab.grab(xdisplay=self.display)
            encoded = io.BytesIO()
            image.convert("RGB").save(encoded, format="JPEG", quality=self.quality)
            return {
                "data": base64.b64encode(encoded.getvalue()).decode("ascii"),
                "width": image.width,
                "height": image.height,
            }

        frame = await asyncio.to_thread(grab)
        self.width, self.height = frame["width"], frame["height"]
        return frame

    async def _run(self, *args, text=None):
        process = await asyncio.create_subprocess_exec(
            "xdotool",
            *args,
            env={**os.environ, "DISPLAY": self.display},
            stdin=asyncio.subprocess.PIPE
            if text is not None
            else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(
                process.communicate(text.encode("utf-8") if text is not None else None),
                max(5, len(text) * 0.03 + 3) if text is not None else 5,
            )
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if process.returncode:
            raise RuntimeError("Window input failed; input was not replayed")

    async def input(self, event):
        if not isinstance(event, dict):
            return False
        kind = event.get("kind")
        if kind in ("click", "wheel"):
            try:
                if any(isinstance(event.get(key), bool) for key in ("x", "y")):
                    return False
                x, y = float(event.get("x", -1)), float(event.get("y", -1))
            except (TypeError, ValueError, OverflowError):
                return False
            if not (
                math.isfinite(x)
                and math.isfinite(y)
                and 0 <= x < self.width
                and 0 <= y < self.height
            ):
                return False
            if kind == "click":
                await self._run("mousemove", str(round(x)), str(round(y)), "click", "1")
            else:
                try:
                    delta = float(event.get("dy", 0))
                except (TypeError, ValueError, OverflowError):
                    return False
                if not math.isfinite(delta):
                    return False
                if delta:
                    await self._run(
                        "mousemove",
                        str(round(x)),
                        str(round(y)),
                        "click",
                        "--repeat",
                        str(min(8, max(1, round(abs(delta) / 80)))),
                        "4" if delta < 0 else "5",
                    )
            return True
        if kind == "text":
            text = event.get("text")
            if (
                not isinstance(text, str)
                or not 0 < len(text) <= self.max_text
                or any(ord(char) < 32 for char in text)
            ):
                return False
            # Stdin keeps passwords out of process arguments. Unicode symbols
            # temporarily change X11 key mappings. Space those changes so Chrome
            # consumes each key before libxdo restores/reuses its mapping.
            await self._run(
                "type",
                "--clearmodifiers",
                "--delay",
                "25" if not text.isascii() else "1",
                "--file",
                "-",
                text=text,
            )
            return True
        if kind == "key":
            keys = {
                "Tab": "Tab",
                "Enter": "Return",
                "Backspace": "BackSpace",
                "Delete": "Delete",
                "Escape": "Escape",
                "ArrowLeft": "Left",
                "ArrowRight": "Right",
                "ArrowUp": "Up",
                "ArrowDown": "Down",
                "Home": "Home",
                "End": "End",
                "SelectAll": "ctrl+a",
                "AddressBar": "ctrl+l",
                "NewTab": "ctrl+t",
                "NextTab": "ctrl+Tab",
                "PreviousTab": "ctrl+shift+Tab",
                "CloseTab": "ctrl+w",
            }
            key = keys.get(event.get("key"))
            if key:
                await self._run(
                    "key",
                    "--clearmodifiers",
                    "shift+" + key if event.get("shift") else key,
                )
                return True
        return False
