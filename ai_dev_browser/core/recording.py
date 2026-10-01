"""Cross-process recording control. Capture and encoding live in _recorder.py."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from ._tab import Tab
from .config import DEFAULT_BASE_DIR, resolve_output_dir
from .errors import RecordingError


def _state_root() -> Path:
    return Path(
        os.environ.get("AI_DEV_BROWSER_RECORDING_DIR", DEFAULT_BASE_DIR / "recordings")
    )


def _write_json(path: Path, value: dict):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    # Windows can briefly deny opens/renames while a file is delete-pending
    # (including antivirus scanning). Retry that specific OS sharing race.
    for attempt in range(100):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 99:
                raise
            time.sleep(0.01)


def _read_state(folder: Path) -> dict:
    for attempt in range(100):
        try:
            return json.loads((folder / "state.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except PermissionError:
            if attempt == 99:
                raise
            time.sleep(0.01)
    return {}


async def page_record_start(
    tab: Tab,
    fps: int = 10,
    out: str | None = None,
    max_duration: float = 300,
) -> dict:
    """Use when: you need a GIF demo or before/after recording; returns recording_id for page_record_stop.

    Returns {recording_id, recording, path, ...} only after receiving the first
    frame. Capture continues after this command exits; use click/type/page_goto
    normally, including navigation, then page_record_stop. One recording per tab.
    For a single still image, use page_screenshot. Records this tab's
    viewport (up to 1280x720), without audio; keep it visible in extension mode.
    Only a successful stop publishes the GIF. Do not close the tab before stop.
    Files are limited to 10 MB for sharing; lower fps or shorten the interaction
    if this limit is reached.

    Args:
        tab: Tab to record, pinned for the entire recording.
        fps: Maximum output frames per second, integer 1 to 30 (default 10).
            Static frames keep their real elapsed duration.
        out: New .gif output path. Defaults to output/recording-<id>.gif;
            honors AI_DEV_BROWSER_OUTPUT_DIR. Existing files are never replaced.
        max_duration: Safety limit in seconds, 1 to 600 (default 300).
            Reaching it fails the recording; stop before the limit to save.

    Failure:
        Fix the reported cause and start a new recording. Keep the tab visible
        and connected; stop an existing recording before starting another on
        that tab. An older extension bridge must be restarted after upgrading.
    """
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 30:
        raise RecordingError("fps must be an integer from 1 to 30", "validation")
    if not 1 <= max_duration <= 600:
        raise RecordingError("max_duration must be from 1 to 600 seconds", "validation")
    recording_id = uuid.uuid4().hex
    path = (
        Path(out).expanduser()
        if out
        else resolve_output_dir() / f"recording-{recording_id}.gif"
    ).resolve()
    if path.suffix.lower() != ".gif":
        raise RecordingError("out must end in .gif", "validation")
    if path.exists():
        raise RecordingError(f"Output already exists: {path}", "conflict")
    path.parent.mkdir(parents=True, exist_ok=True)
    folder = _state_root().resolve() / recording_id
    folder.mkdir(parents=True, mode=0o700)
    config = {
        "recording_id": recording_id,
        "url": tab._connection.websocket_url,
        "tab_id": str(tab.target_id),
        "workspace": str(Path.cwd().resolve()),
        "path": str(path),
        "fps": fps,
        "max_duration": max_duration,
        "extension": tab.browser.transport == "extension",
    }
    _write_json(folder / "config.json", config)
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        with (folder / "worker.log").open("wb") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "ai_dev_browser.core._recorder", str(folder)],
                stderr=log,
                **kwargs,
            )
    except OSError:
        (folder / "acknowledged").touch()
        raise
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = _read_state(folder)
            if state.get("status") == "recording":
                return {
                    "recording": True,
                    "recording_id": recording_id,
                    "path": str(path),
                    "tab_id": config["tab_id"],
                    "fps": fps,
                    "max_duration": max_duration,
                }
            if state.get("status") == "failed":
                raise RecordingError(
                    state["error"], state.get("error_code", "recording_failed")
                )
            if process.poll() is not None:
                raise RecordingError(
                    f"Recorder exited during startup; see {folder / 'worker.log'}"
                )
            await asyncio.sleep(0.05)
        raise RecordingError(
            "No screencast frame received within 20 seconds; keep the tab visible"
        )
    except BaseException:
        (folder / "stop").touch()
        if process.poll() is None:
            process.terminate()
        await asyncio.to_thread(process.wait)
        (folder / "acknowledged").touch()
        path.with_name(f".{path.name}.{recording_id}.partial").unlink(missing_ok=True)
        raise


async def page_record_stop(recording_id: str | None = None) -> dict:
    """Use when: interaction is finished; finalize its GIF and return the saved path.

    Returns {saved, path, size_bytes, frames, duration_seconds, ...}; success
    confirms the file is complete. No browser connection is needed, so a closed
    tab or failed worker still produces a recording error. Repeating stop with
    the same ID returns the saved result. An interrupted recording is never saved.

    Args:
        recording_id: ID returned by page_record_start. Omit only when this
            working directory has exactly one unfinished recording. Pass the ID
            to stop from another directory or choose among multiple recordings.

    Failure:
        A failed recording cannot be repaired by retrying stop. Read the error,
        fix the cause, and record the interaction again. For an ambiguous or
        missing selection, pass the recording_id returned by page_record_start.
    """
    root = _state_root().resolve()
    if recording_id is None:
        candidates = []
        for config_path in root.glob("*/config.json"):
            config = json.loads(config_path.read_text(encoding="utf-8"))
            folder = config_path.parent
            if (
                config.get("workspace") == str(Path.cwd().resolve())
                and not (folder / "acknowledged").exists()
                and _read_state(folder).get("status") != "saved"
            ):
                candidates.append(folder.name)
        if len(candidates) != 1:
            raise RecordingError(
                f"Expected one unfinished recording in this directory, found {len(candidates)}; "
                f"specify recording_id. Candidates: {candidates}",
                "validation",
            )
        recording_id = candidates[0]
    if not re.fullmatch(r"[0-9a-f]{32}", recording_id):
        raise RecordingError(
            "Invalid recording_id; use the ID returned by page_record_start",
            "validation",
        )
    folder = root / recording_id
    if not (folder / "config.json").is_file():
        raise RecordingError(f"Recording not found: {recording_id}", "not_found")
    (folder / "stop").touch()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        state = _read_state(folder)
        if state.get("status") == "saved":
            result = state["result"]
            path = Path(result["path"])
            if not path.is_file() or path.stat().st_size != result["size_bytes"]:
                raise RecordingError(
                    f"Saved recording is missing or was changed: {path}"
                )
            return result
        if state.get("status") == "failed":
            (folder / "acknowledged").touch()
            raise RecordingError(
                state["error"], state.get("error_code", "recording_failed")
            )
        if state and time.time() - state.get("heartbeat", 0) > 10:
            (folder / "abort").touch()
            (folder / "acknowledged").touch()
            raise RecordingError(
                "Recorder heartbeat lost; recording is incomplete and has not been published"
            )
        await asyncio.sleep(0.05)
    (folder / "abort").touch()
    (folder / "acknowledged").touch()
    raise RecordingError(
        f"Recorder did not finish within 20 seconds; inspect {folder / 'worker.log'}"
    )
