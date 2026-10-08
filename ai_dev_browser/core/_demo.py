"""Recording-scoped input state and output-only interaction graphics.

No page DOM, keyboard text, or system cursor is changed by the graphics.
Input logs contain only acknowledged mouse coordinates and button transitions.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
import uuid
from pathlib import Path

from PIL import Image, ImageDraw

from .errors import RecordingError

CLICK_SECONDS = 0.55
TYPE_SECONDS = 0.11


def index_path(url: str, tab_id: str) -> Path:
    from .recording import _state_root

    key = hashlib.sha256(f"{url}\n{tab_id}".encode()).hexdigest()
    return _state_root().resolve() / f"{key}.demo.json"


def session(tab, demo_only=True):
    """The same recording is discovered by SDK objects and fresh CLI processes."""
    if not getattr(tab, "_connection", None):
        return None
    from .recording import _read_json

    path = index_path(tab._connection.websocket_url, str(tab.target_id))
    try:
        index = _read_json(path)
        if not index:
            return None
        folder = Path(index["folder"])
        state = _read_json(folder / "state.json")
        if state.get("status") != "recording" or time.time() - state["heartbeat"] > 10:
            return None
        if demo_only and not state.get("demo", True):
            return None
        cached = getattr(tab, "_demo_session", None)
        if cached is None or cached.folder != folder:
            cached = Session(folder)
            tab._demo_session = cached
        return cached
    except FileNotFoundError:
        return None


class Session:
    def __init__(self, folder):
        self.folder = folder
        self.log = folder / "events" / f"{os.getpid()}-{uuid.uuid4().hex}.jsonl"

    def publish(self, filename, value):
        from .recording import _write_json

        try:
            _write_json(self.folder / filename, value)
        except OSError as exc:
            (self.folder / "abort").touch()
            raise RecordingError(f"Recording input state failed: {exc}") from exc

    def pointer(self):
        from .recording import _read_json

        return _read_json(self.folder / "pointer.json") or None

    def record(self, params, timestamp, point=None):
        if params.get("type") not in ("mouseMoved", "mousePressed", "mouseReleased"):
            return
        x, y = point or (params["x"], params["y"])
        previous = self.pointer() or {}
        event = {
            "time": timestamp,
            "type": params["type"],
            "x": x,
            "y": y,
            "buttons": params.get("buttons", 0),
            "button": params.get("button", "none"),
        }
        # Only a press/release changes button state; moves can omit buttons.
        if event["type"] == "mousePressed":
            event["held"] = True
        elif event["type"] == "mouseReleased":
            event["held"] = False
        else:
            event["held"] = bool(event["buttons"] or previous.get("held", False))
        try:
            with self.log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event) + "\n")
            self.publish("pointer.json", event)
        except OSError as exc:
            (self.folder / "abort").touch()
            raise RecordingError(
                f"Demo input log failed; recording is incomplete: {exc}"
            ) from exc


class Overlay:
    """Read bounded per-process input streams and draw in capture coordinates."""

    def __init__(self, folder):
        self.folder = folder
        self.offsets = {}
        self.events = []
        self.pointer = None
        self.pulses = []
        self.trail = []
        self.bytes_read = 0

    def update(self, now):
        for path in (self.folder / "events").glob("*.jsonl"):
            with path.open("rb") as handle:
                handle.seek(self.offsets.get(path, 0))
                while True:
                    start = handle.tell()
                    line = handle.readline()
                    if not line:
                        break
                    if not line.endswith(b"\n"):
                        handle.seek(start)  # An input process is still writing.
                        break
                    self.bytes_read += len(line)
                    if self.bytes_read > 16_000_000:
                        raise RecordingError("Demo input log exceeded its safety limit")
                    self.events.append(json.loads(line))
                self.offsets[path] = handle.tell()
        self.events.sort(key=lambda event: event["time"])
        future = []
        for event in self.events:
            if event["time"] > now:
                future.append(event)
                continue
            if self.pointer is None or event["time"] >= self.pointer["time"]:
                self.pointer = event
                self.trail.append(event)
            if event["type"] == "mouseReleased":
                self.pulses.append(event)
        self.events = future
        self.trail = [e for e in self.trail if now - e["time"] < 0.22]
        self.pulses = [e for e in self.pulses if now - e["time"] < CLICK_SECONDS]

    def animating(self, now):
        self.update(now)
        return bool(self.pulses or self.trail)

    def render(self, source, now, metadata):
        self.update(now)
        frame = source.convert("RGBA")
        graphics = Image.new("RGBA", frame.size)
        draw = ImageDraw.Draw(graphics)
        scale = frame.width / max(1, metadata.get("deviceWidth", frame.width))
        scale *= metadata.get("pageScaleFactor", 1)

        def point(event):
            return event["x"] * scale, event["y"] * scale

        for event in self.trail:
            x, y = point(event)
            alpha = round(90 * max(0, 1 - (now - event["time"]) / 0.22))
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(37, 99, 235, alpha))
        for event in self.pulses:
            x, y = point(event)
            progress = max(0, (now - event["time"]) / CLICK_SECONDS)
            radius = 8 + 24 * progress
            alpha = round(220 * (1 - progress))
            draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                outline=(37, 99, 235, alpha),
                width=3,
            )
        if self.pointer is not None:
            x, y = point(self.pointer)
            held = self.pointer["held"]
            if held:
                draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(37, 99, 235, 90))
            size = 0.85 if held else 1.0
            vertices = [
                (0, 0),
                (0, 23),
                (6, 17),
                (11, 27),
                (15, 25),
                (10, 15),
                (19, 15),
            ]
            draw.polygon(
                [(x + a * size, y + b * size) for a, b in vertices],
                fill=(37, 99, 235, 255) if held else (255, 255, 255, 255),
                outline=(15, 23, 42, 255),
                width=2,
            )
        return Image.alpha_composite(frame, graphics).convert("RGB")


def move_duration(start, end):
    return min(0.9, 0.35 + math.dist(start, end) / 1800)
