"""Browser worker pool module.

Provides parallel task execution with multiple browser workers.

Example:
    from ai_dev_browser.pool import BrowserPool, Job, JobResult

    async with BrowserPool(MyClient, workers=3) as pool:
        await pool.run("fetch", "https://example.com")
        results = await pool.wait()
"""

from .job import Job, JobResult, JobStatus
from .persistence import PoolState, load_state, save_state
from .pool import BrowserPool
from .worker import Worker, WorkerStats, WorkerStatus

__all__ = [
    # Main pool class
    "BrowserPool",
    # Job types
    "Job",
    "JobResult",
    "JobStatus",
    # Worker types
    "Worker",
    "WorkerStats",
    "WorkerStatus",
    # Persistence
    "PoolState",
    "load_state",
    "save_state",
]
