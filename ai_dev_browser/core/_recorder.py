"""Detached screencast worker. No reconnects: any capture gap invalidates the GIF."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import sys
import time
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path

import websockets
from PIL import GifImagePlugin, Image, ImageChops, ImageOps

from ._demo import Overlay, index_path
from .errors import RecordingError
from .recording import _read_json, _write_json

MAX_GIF_BYTES = 10_000_000  # Fits Feishu's documented 10 MB GIF preview limit.


@contextmanager
def _exclusive_lock(root: Path, key: str):
    """OS releases the lock even if the recorder is killed; no stale PID reuse."""
    path = root / (hashlib.sha256(key.encode()).hexdigest() + ".lock")
    with path.open("a+b") as handle:
        if not path.stat().st_size:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RecordingError(
                "Recording tab or output already in use", "conflict"
            ) from exc
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class _Gif:
    """Encode one frame at a time, retaining only the current frame in memory.

    GIF durations are centiseconds. Quantize cumulative time, not each delta,
    to avoid drift. A held frame includes quiet time until the next change/stop.
    Pillow's getheader/getdata supply GIF headers, palettes and LZW encoding.
    """

    def __init__(self, handle):
        self.handle = handle
        self.pending = None
        self.size = None
        self.start = 0.0
        self.ticks = 0
        self.frames = 0
        self.previous = None

    def push(self, data, timestamp: float):
        if isinstance(data, Image.Image):
            frame = data.convert("RGB")
        else:
            with Image.open(
                io.BytesIO(base64.b64decode(data, validate=True))
            ) as source:
                frame = source.convert("RGB")
        if self.size is None:
            self.size = frame.size
            self.start = timestamp
        if frame.size != self.size:
            # Keep a fixed GIF canvas when a window is resized during capture.
            frame = ImageOps.pad(frame, self.size, color="white")
        if (
            self.pending is not None
            and ImageChops.difference(frame, self.pending).getbbox() is None
        ):
            return  # Hold an identical frame for its real elapsed duration.
        if self.pending is None:
            header, _ = GifImagePlugin.getheader(
                frame.quantize(colors=256), info={"loop": 0}
            )
            for block in header:
                self.handle.write(block)
        else:
            self._flush(timestamp)
        self.pending = frame

    def _flush(self, timestamp: float):
        ticks = max(self.ticks + 1, round((timestamp - self.start) * 100))
        bounds = (
            (0, 0, *self.pending.size)
            if self.previous is None
            else ImageChops.difference(self.pending, self.previous).getbbox()
        )
        if bounds is None:
            bounds = (0, 0, 1, 1)
        # Only encode changed pixels. A moving cursor on a static page must
        # not consume the 10 MB budget by repeatedly encoding the whole page.
        encoded = self.pending.crop(bounds).quantize(colors=256)
        for block in GifImagePlugin.getdata(
            encoded,
            offset=bounds[:2],
            duration=(ticks - self.ticks) * 10,
            include_color_table=True,
            disposal=1,
        ):
            self.handle.write(block)
        self.ticks = ticks
        self.frames += 1
        self.previous = self.pending
        if self.handle.tell() + 1 > MAX_GIF_BYTES:  # Reserve the GIF trailer.
            raise RecordingError(
                "Recording exceeded the 10 MB GIF sharing limit; use a lower fps "
                "or record a shorter interaction"
            )

    def finish(self, timestamp: float):
        if self.pending is None:
            raise RecordingError("Recording received no frames")
        self._flush(timestamp)
        self.handle.write(b";")
        self.handle.flush()
        os.fsync(self.handle.fileno())


class _Capture:
    def __init__(self, ws):
        self.ws = ws
        self.sequence = 0
        self.pending: dict = {}
        self.frames: asyncio.Queue = asyncio.Queue(maxsize=16)
        self.latest = None
        self.started = asyncio.Event()
        self.metadata = {}

    async def command(self, method, params=None):
        self.sequence += 1
        mid = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[mid] = future
        try:
            await self.ws.send(
                json.dumps({"id": mid, "method": method, "params": params or {}})
            )
            try:
                return await asyncio.wait_for(future, 5)
            except asyncio.TimeoutError as exc:
                raise RecordingError(
                    f"Capture command timed out after 5s: {method}"
                ) from exc
        finally:
            self.pending.pop(mid, None)

    async def receive(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if "id" in msg:
                    future = self.pending.get(msg["id"])
                    if future is not None and not future.done():
                        if "error" in msg:
                            future.set_exception(RecordingError(str(msg["error"])))
                        else:
                            future.set_result(msg.get("result", {}))
                elif msg.get("method") == "Page.screencastFrame":
                    self.frames.put_nowait((msg["params"], time.monotonic()))
                elif msg.get("method") in (
                    "Inspector.detached",
                    "Inspector.targetCrashed",
                ):
                    raise RecordingError(
                        f"Recording target detached: {msg.get('params')}"
                    )
            raise RecordingError("Capture connection closed during recording")
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(
                        RecordingError("Capture connection lost during recording")
                    )

    async def consume(self):
        while True:
            params, received = await self.frames.get()
            try:
                # ACK every input frame, even those omitted by the FPS cap.
                await self.command(
                    "Page.screencastFrameAck", {"sessionId": params["sessionId"]}
                )
                self.latest = (params["data"], received)
                self.metadata = params.get("metadata", {})
                self.started.set()
            finally:
                self.frames.task_done()


async def _record(folder: Path, config: dict, partial: Path) -> dict:
    async with websockets.connect(
        config["url"], max_size=16 * 1024 * 1024, open_timeout=5, close_timeout=2
    ) as ws:
        capture = _Capture(ws)
        receiver = asyncio.create_task(capture.receive())
        consumer = asyncio.create_task(capture.consume())
        tasks = [receiver, consumer]
        screencast_started = False
        demo_index = None
        overlay = Overlay(folder) if config.get("demo", True) else None
        try:
            if config.get("extension"):
                status = await capture.command("_bridge.status")
                if not status.get("concurrent_events"):
                    raise RecordingError(
                        "Extension bridge is too old for recording. Restart it with "
                        "browser_disconnect then browser_connect --transport extension",
                        "conflict",
                    )
            await capture.command("Page.enable")
            viewport = _read_json(folder / "viewport.json")
            await capture.command("Emulation.setDeviceMetricsOverride", viewport)
            await capture.command(
                "Page.startScreencast",
                {
                    "format": "png",
                    "maxWidth": 1280,
                    "maxHeight": 720,
                    "everyNthFrame": 1,
                },
            )
            screencast_started = True
            ready = asyncio.create_task(capture.started.wait())
            try:
                done, _ = await asyncio.wait(
                    [ready, *tasks], timeout=10, return_when=asyncio.FIRST_COMPLETED
                )
                for task in tasks:
                    if task in done:
                        task.result()  # Preserve the actual disconnect/ACK failure.
                if not capture.started.is_set():
                    raise RecordingError(
                        "No screencast frame received within 10 seconds; keep the tab visible"
                    )
            finally:
                ready.cancel()
                await asyncio.gather(ready, return_exceptions=True)
            if overlay:
                (folder / "events").mkdir()
            demo_index = index_path(config["url"], config["tab_id"])
            _write_json(demo_index, {"folder": str(folder)})

            def render(data, timestamp, metadata=None):
                if overlay is None:
                    return data
                with Image.open(
                    io.BytesIO(base64.b64decode(data, validate=True))
                ) as source:
                    return overlay.render(
                        source, timestamp, metadata or capture.metadata
                    )

            with partial.open("xb") as output:
                gif = _Gif(output)
                data, started = capture.latest
                await asyncio.to_thread(gif.push, render(data, started), started)
                last_frame = started
                last_received = started
                last_health = 0.0
                last_state = 0.0
                while True:
                    if (folder / "abort").exists():
                        raise RecordingError(
                            "Recording aborted after the controller lost contact"
                        )
                    for task in tasks:
                        if task.done():
                            task.result()
                    now = time.monotonic()
                    requested_viewport = _read_json(folder / "viewport.json")
                    if requested_viewport != viewport:
                        await capture.command(
                            "Emulation.setDeviceMetricsOverride", requested_viewport
                        )
                        viewport = requested_viewport
                    if now - started >= config["max_duration"]:
                        raise RecordingError(
                            "Recording reached max_duration before stop; no GIF published"
                        )
                    if now - last_health >= 0.2:
                        # Quiet pages legitimately emit no frames. Probe the target
                        # separately so a detached extension cannot look like idle.
                        metrics = await capture.command("Page.getLayoutMetrics")
                        actual = metrics["cssLayoutViewport"]
                        if (actual["clientWidth"], actual["clientHeight"]) != (
                            viewport["width"],
                            viewport["height"],
                        ):
                            await capture.command(
                                "Emulation.setDeviceMetricsOverride", viewport
                            )
                        last_health = now
                    if now - last_state >= 0.5:
                        _write_json(
                            folder / "state.json",
                            {
                                "status": "recording",
                                "heartbeat": time.time(),
                                "pid": os.getpid(),
                                "demo": config.get("demo", True),
                            },
                        )
                        last_state = now
                    if (folder / "stop").exists() and (
                        not overlay or not overlay.animating(now)
                    ):
                        break
                    latest_data, received = capture.latest
                    if (
                        received > last_received or overlay is not None
                    ) and now - last_frame >= 1 / config["fps"]:
                        await asyncio.to_thread(gif.push, render(latest_data, now), now)
                        last_frame = now
                        last_received = received
                    await asyncio.sleep(0.02)
                # A successful stop requires a live target and an acknowledged
                # stop. Never reconnect and splice a gap into an apparent success.
                await capture.command("Page.getLayoutMetrics")
                await capture.command("Page.stopScreencast")
                await asyncio.wait_for(capture.frames.join(), 5)
                for task in tasks:
                    if task.done():
                        task.result()
                latest_data, received = capture.latest
                if received > last_received:
                    stamp = time.monotonic()
                    await asyncio.to_thread(gif.push, render(latest_data, stamp), stamp)
                # Navigation can finish before Chrome delivers its next screencast
                # event. Capture the final viewport after stopping the stream so
                # an immediate stop cannot silently save the previous page as the
                # ending. _Gif fits this snapshot to the existing bounded canvas.
                await capture.command("Emulation.setDeviceMetricsOverride", viewport)
                metrics = await capture.command("Page.getLayoutMetrics")
                layout = metrics["cssLayoutViewport"]
                final_metadata = {
                    "deviceWidth": layout["clientWidth"],
                    "pageScaleFactor": metrics["cssVisualViewport"]["scale"],
                }
                final = await capture.command(
                    "Page.captureScreenshot",
                    {
                        "format": "png",
                        "fromSurface": True,
                        "captureBeyondViewport": False,
                    },
                )
                for task in tasks:
                    if task.done():
                        task.result()
                stamp = time.monotonic()
                await asyncio.to_thread(
                    gif.push, render(final["data"], stamp, final_metadata), stamp
                )
                await asyncio.to_thread(gif.finish, time.monotonic())
                result = {
                    "saved": True,
                    "recording_id": config["recording_id"],
                    "path": config["path"],
                    "size_bytes": output.tell(),
                    "frames": gif.frames,
                    "duration_seconds": gif.ticks / 100,
                    "width": gif.size[0],
                    "height": gif.size[1],
                    "fps": config["fps"],
                    "demo": config.get("demo", True),
                }
            return result
        finally:
            if demo_index is not None:
                demo_index.unlink(missing_ok=True)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if screencast_started:
                with suppress(Exception):
                    await capture.ws.send(
                        json.dumps({"id": 0, "method": "Page.stopScreencast"})
                    )


def main():
    folder = Path(sys.argv[1])
    config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    partial = Path(config["path"]).with_name(
        f".{Path(config['path']).name}.{config['recording_id']}.partial"
    )
    published = False
    try:
        with ExitStack() as stack:
            stack.enter_context(_exclusive_lock(folder.parent, config["url"]))
            stack.enter_context(
                _exclusive_lock(folder.parent, os.path.normcase(config["path"]))
            )
            if Path(config["path"]).exists():
                raise RecordingError("Output already exists", "conflict")
            result = asyncio.run(_record(folder, config, partial))
            if (folder / "abort").exists():
                raise RecordingError("Recording aborted before publication")
            # Atomic publication, same filesystem, no overwrite race.
            os.link(partial, config["path"])
            published = True
            _write_json(folder / "state.json", {"status": "saved", "result": result})
    except Exception as exc:
        if published:
            Path(config["path"]).unlink(missing_ok=True)
        _write_json(
            folder / "state.json",
            {
                "status": "failed",
                "error": f"Recording failed: {type(exc).__name__}: {exc}",
                "error_code": getattr(exc, "error_code", "recording_failed"),
            },
        )
    finally:
        partial.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
