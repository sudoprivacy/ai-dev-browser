"""Worker class for BrowserPool.

This module defines the Worker abstraction that manages a single browser instance:
- Worker: Represents one browser worker in the pool
- WorkerStatus: Current state of a worker
- WorkerStats: Success/failure statistics

Example:
    worker = Worker(worker_id=0, port=9350)
    worker.mark_busy(job)
    # ... execute job ...
    worker.mark_idle()
    print(f"Success rate: {worker.stats.success_rate:.1%}")
"""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from .job import Job


class WorkerStatus(Enum):
    """
    Status of a worker in the pool.

    States:
        IDLE: Ready to accept new jobs
        BUSY: Currently executing a job
        STOPPING: Will finish current job then stop
        STOPPED: Fully stopped, client closed
        ERROR: Worker encountered an error
    """

    IDLE = "idle"
    BUSY = "busy"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class WorkerStats:
    """
    Statistics for a worker.

    Attributes:
        success: Number of successfully completed jobs
        fail: Number of failed jobs
        total_time: Total execution time in seconds

    Example:
        stats = worker.stats
        print(f"Completed {stats.total} jobs, {stats.success_rate:.1%} success rate")
    """

    success: int = 0
    fail: int = 0
    total_time: float = 0.0  # seconds

    @property
    def total(self) -> int:
        """Total jobs processed (success + fail)."""
        return self.success + self.fail

    @property
    def success_rate(self) -> float:
        """Success rate as a float between 0 and 1."""
        if self.total == 0:
            return 0.0
        return self.success / self.total


@dataclass
class Worker:
    """
    A browser worker that executes jobs.

    Manages a single browser instance and tracks job execution state.
    The client field holds the browser client (type depends on pool configuration).

    Attributes:
        worker_id: Unique identifier for this worker
        port: Chrome debugging port assigned to this worker
        client: Browser client instance (generic type)
        status: Current worker status
        current_job: Job being executed, if any
        stats: Success/failure statistics

    Example:
        worker = Worker(worker_id=0, port=9350)
        await client.__aenter__()
        worker.client = client

        # Execute job
        worker.mark_busy(job)
        result = await client.some_method()
        worker.mark_idle()
    """

    worker_id: int
    port: int
    client: Any = None  # Generic client type
    status: WorkerStatus = WorkerStatus.IDLE
    current_job: "Job | None" = None
    stats: WorkerStats = field(default_factory=WorkerStats)
    _task_done_event: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self):
        # Set event initially (no task running)
        self._task_done_event.set()

    async def wait_current_task(self, timeout: float | None = None) -> bool:
        """
        Wait for the current task to complete.

        Args:
            timeout: Maximum time to wait in seconds. None = wait forever.

        Returns:
            True if task completed, False if timeout.

        Example:
            if worker.status == WorkerStatus.BUSY:
                await worker.wait_current_task(timeout=30)
        """
        try:
            await asyncio.wait_for(self._task_done_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def mark_busy(self, job: "Job"):
        """Mark worker as busy with a job."""
        self.status = WorkerStatus.BUSY
        self.current_job = job
        self._task_done_event.clear()

    def mark_idle(self):
        """Mark worker as idle (task completed)."""
        self.status = WorkerStatus.IDLE
        self.current_job = None
        self._task_done_event.set()

    def mark_stopping(self):
        """Mark worker as stopping (will finish current task then stop)."""
        self.status = WorkerStatus.STOPPING

    def mark_stopped(self):
        """Mark worker as fully stopped."""
        self.status = WorkerStatus.STOPPED
        self.current_job = None
        self._task_done_event.set()

    def to_dict(self) -> dict:
        """Serialize worker state for status reporting."""
        return {
            "worker_id": self.worker_id,
            "port": self.port,
            "status": self.status.value,
            "current_job_id": self.current_job.job_id if self.current_job else None,
            "stats": {
                "success": self.stats.success,
                "fail": self.stats.fail,
                "total": self.stats.total,
                "success_rate": round(self.stats.success_rate, 2),
            },
        }
