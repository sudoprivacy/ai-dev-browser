"""State persistence for BrowserPool.

This module provides atomic state persistence for the browser pool:
- PoolState: Serializable snapshot of pool state
- save_state: Atomic write to file (temp + rename)
- load_state: Safe loading with corruption handling

Example:
    state = PoolState()
    state.completed[job.job_id] = result
    save_state(state, Path("pool_state.json"))

    # Later...
    loaded = load_state(Path("pool_state.json"))
    if loaded:
        print(f"Restored {len(loaded.completed)} completed jobs")
"""

import contextlib
import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .job import Job, JobResult

STATE_VERSION = 1


@dataclass
class PoolState:
    """
    Serializable state of the worker pool.

    Attributes:
        version: State format version for migration
        last_updated: Timestamp of last save
        completed: Map of job_id -> JobResult for finished jobs
        pending: Jobs waiting in queue
        in_progress: Jobs currently being processed

    Example:
        state = PoolState()
        state.pending.append(job)
        state.completed[job.job_id] = result
    """

    version: int = STATE_VERSION
    last_updated: datetime = field(default_factory=datetime.now)
    completed: dict[str, "JobResult"] = field(default_factory=dict)
    pending: list["Job"] = field(default_factory=list)
    in_progress: list["Job"] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize state to dict."""
        return {
            "version": self.version,
            "last_updated": self.last_updated.isoformat(),
            "completed": {job_id: result.to_dict() for job_id, result in self.completed.items()},
            "pending": [job.to_dict() for job in self.pending],
            "in_progress": [job.to_dict() for job in self.in_progress],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PoolState":
        """Deserialize state from dict."""
        from .job import Job, JobResult

        version = data.get("version", 1)
        if version != STATE_VERSION:
            # Handle version migration if needed in the future
            pass

        return cls(
            version=version,
            last_updated=datetime.fromisoformat(data["last_updated"]),
            completed={
                job_id: JobResult.from_dict(result_data)
                for job_id, result_data in data.get("completed", {}).items()
            },
            pending=[Job.from_dict(j) for j in data.get("pending", [])],
            in_progress=[Job.from_dict(j) for j in data.get("in_progress", [])],
        )


def save_state(state: PoolState, file_path: Path | str) -> None:
    """
    Save pool state to file atomically.

    Uses atomic write (write to temp file, then rename) to prevent corruption
    from crashes or power failures during write.

    Args:
        state: The pool state to save
        file_path: Path to the state file

    Example:
        save_state(pool_state, "progress.json")
    """
    file_path = Path(file_path)
    state.last_updated = datetime.now()
    data = state.to_dict()

    # Ensure parent directory exists
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file in same directory for atomic rename
    temp_fd, temp_path = tempfile.mkstemp(
        dir=file_path.parent, prefix=".pool_state_", suffix=".tmp"
    )
    try:
        with open(temp_fd, "w") as f:
            json.dump(data, f, indent=2)
        # Atomic rename
        Path(temp_path).replace(file_path)
    except Exception:
        # Clean up temp file on error
        with contextlib.suppress(OSError):
            Path(temp_path).unlink()
        raise


def load_state(file_path: Path | str) -> PoolState | None:
    """
    Load pool state from file.

    Handles missing files and corrupted data gracefully.

    Args:
        file_path: Path to the state file

    Returns:
        PoolState if file exists and is valid, None otherwise.

    Example:
        state = load_state("progress.json")
        if state:
            print(f"Resuming with {len(state.pending)} pending jobs")
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return None

    try:
        with open(file_path) as f:
            data = json.load(f)
        return PoolState.from_dict(data)
    except (json.JSONDecodeError, KeyError, ValueError):
        # Corrupted or invalid state file
        return None
