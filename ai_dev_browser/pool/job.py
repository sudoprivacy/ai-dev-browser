"""Job models for BrowserPool.

This module defines the core data structures for job management:
- Job: A task to be executed by a browser worker
- JobResult: The outcome of a completed job
- JobStatus: Current state of a job

Example:
    job = Job(task_type="fetch", args=("https://example.com",))
    result = JobResult(job_id=job.job_id, success=True, data={"title": "Example"})
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class JobStatus(Enum):
    """Status of a job in the queue."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    """
    A task to be executed by a browser worker.

    Attributes:
        task_type: Name of the client method to call (e.g., "fetch", "scrape")
        args: Positional arguments for the method
        kwargs: Keyword arguments for the method
        job_id: Unique identifier (auto-generated UUID)
        retries: Number of retry attempts made
        max_retries: Maximum retries allowed (-1 = unlimited)
        created_at: Timestamp when job was created
        status: Current job status

    Example:
        job = Job(
            task_type="download",
            args=("https://example.com/file.pdf",),
            kwargs={"output": "file.pdf"},
            max_retries=3,
        )
    """

    task_type: str
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    job_id: str = field(default_factory=lambda: str(uuid4()))
    retries: int = 0
    max_retries: int = -1  # -1 = unlimited
    created_at: datetime = field(default_factory=datetime.now)
    status: JobStatus = JobStatus.PENDING

    def to_dict(self) -> dict:
        """Serialize job for persistence."""
        return {
            "job_id": self.job_id,
            "task_type": self.task_type,
            "args": list(self.args),
            "kwargs": self.kwargs,
            "retries": self.retries,
            "max_retries": self.max_retries,
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        """Deserialize job from persistence."""
        return cls(
            job_id=data["job_id"],
            task_type=data["task_type"],
            args=tuple(data.get("args", [])),
            kwargs=data.get("kwargs", {}),
            retries=data.get("retries", 0),
            max_retries=data.get("max_retries", -1),
            created_at=datetime.fromisoformat(data["created_at"]),
            status=JobStatus(data.get("status", "pending")),
        )


@dataclass
class JobResult:
    """
    Result of a completed job.

    Attributes:
        job_id: ID of the job this result belongs to
        success: True if job completed without error
        data: Return value from the client method (JSON-serializable)
        error: Error message if job failed (from `str(exception)`)
        error_type: Exception class name if job failed (e.g.
            `"GrokRateLimitError"`). Lets callers branch on exception
            type without string-matching `error`. None on success.
        error_bases: List of exception base-class names from the mro,
            excluding `object` (e.g.
            `["RateLimitError", "RuntimeError", "Exception"]`). Lets
            callers match superclasses when the concrete type is
            domain-specific but the base is standard. Empty on success.
        completed_at: Timestamp when job completed
        worker_id: ID of the worker that executed the job

    Example:
        result = JobResult(
            job_id="abc-123",
            success=True,
            data={"url": "https://example.com", "title": "Example"},
            worker_id=0,
        )

        # Failure branching without text matching:
        if not result.success:
            if result.error_type == "GrokRateLimitError":
                schedule_retry()
            elif "TimeoutError" in result.error_bases:
                ...
    """

    job_id: str
    success: bool
    data: Any = None
    error: str | None = None
    error_type: str | None = None
    error_bases: list[str] = field(default_factory=list)
    completed_at: datetime = field(default_factory=datetime.now)
    worker_id: int | None = None

    @classmethod
    def from_exception(
        cls,
        job_id: str,
        exc: BaseException,
        worker_id: int | None = None,
    ) -> "JobResult":
        """Build a failure result capturing the exception's type + mro.

        Use inside worker exception handlers so callers downstream can
        branch on `error_type` / `error_bases` without parsing
        `error` text.
        """
        cls_chain = type(exc).__mro__
        # mro ends with `object`; drop it. First element is the type
        # itself, which we surface as `error_type`; the rest is bases.
        error_type = cls_chain[0].__name__
        error_bases = [c.__name__ for c in cls_chain[1:] if c is not object]
        return cls(
            job_id=job_id,
            success=False,
            error=str(exc),
            error_type=error_type,
            error_bases=error_bases,
            worker_id=worker_id,
        )

    def to_dict(self) -> dict:
        """Serialize result for persistence."""
        return {
            "job_id": self.job_id,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "error_type": self.error_type,
            "error_bases": self.error_bases,
            "completed_at": self.completed_at.isoformat(),
            "worker_id": self.worker_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JobResult":
        """Deserialize result from persistence."""
        return cls(
            job_id=data["job_id"],
            success=data["success"],
            data=data.get("data"),
            error=data.get("error"),
            error_type=data.get("error_type"),
            error_bases=data.get("error_bases") or [],
            completed_at=datetime.fromisoformat(data["completed_at"]),
            worker_id=data.get("worker_id"),
        )
