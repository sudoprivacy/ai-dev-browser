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
        error: Error message if job failed
        completed_at: Timestamp when job completed
        worker_id: ID of the worker that executed the job

    Example:
        result = JobResult(
            job_id="abc-123",
            success=True,
            data={"url": "https://example.com", "title": "Example"},
            worker_id=0,
        )
    """

    job_id: str
    success: bool
    data: Any = None
    error: str | None = None
    completed_at: datetime = field(default_factory=datetime.now)
    worker_id: int | None = None

    def to_dict(self) -> dict:
        """Serialize result for persistence."""
        return {
            "job_id": self.job_id,
            "success": self.success,
            "data": self.data,
            "error": self.error,
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
            completed_at=datetime.fromisoformat(data["completed_at"]),
            worker_id=data.get("worker_id"),
        )
