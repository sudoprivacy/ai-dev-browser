"""BrowserPool - Manage multiple concurrent browser workers.

This module provides the main pool implementation:
- BrowserPool: Generic pool that works with any async context manager client

Example:
    class MyClient:
        def __init__(self, port: int):
            self.port = port

        async def __aenter__(self):
            self.browser = await connect(self.port)
            return self

        async def __aexit__(self, *args):
            await self.browser.close()

        async def fetch(self, url: str) -> dict:
            return {"url": url, "title": "..."}

    async with BrowserPool(MyClient, workers=3) as pool:
        await pool.run("fetch", "https://example.com")
        results = await pool.wait()
"""

import asyncio
import contextlib
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Literal, Protocol, TypeVar

from ..browser import get_available_port, get_pid_on_port, kill_process_tree
from ..profile import ProfileManager, ProfileMode
from .job import Job, JobResult, JobStatus
from .persistence import PoolState, load_state, save_state
from .worker import Worker, WorkerStats, WorkerStatus

logger = logging.getLogger(__name__)


class BrowserClient(Protocol):
    """Protocol for browser client classes.

    A client must support async context manager protocol and have methods
    that can be called by task_type name.
    """

    async def __aenter__(self) -> "BrowserClient": ...
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None: ...


ClientT = TypeVar("ClientT", bound=BrowserClient)


@dataclass
class _SharedTarget:
    """Internal shared target state for coordinating multiple workers."""

    target: int
    state: dict[str, int] = field(default_factory=dict)  # job_id -> success_count


class BrowserPool(Generic[ClientT]):
    """
    Manage multiple concurrent browser workers with job queuing and persistence.

    A generic pool that works with any async context manager client class.
    The client class must accept a `port` keyword argument in its constructor.

    Features:
        - Multiple concurrent workers, each with isolated Chrome instance
        - Dynamic scaling: add/remove workers at runtime
        - Job queue for task distribution
        - Progress persistence for resume after restart
        - Graceful shutdown: complete current tasks before exit
        - Profile management: shared, per_worker, or temp modes

    Example:
        async with BrowserPool(MyClient, workers=3) as pool:
            # Submit jobs - uses AI-friendly "run" instead of "submit"
            job_id = await pool.run("fetch", url="https://example.com")

            # Dynamically add worker
            await pool.add_worker()

            # Wait for all jobs
            results = await pool.wait()

    Profile modes:
        - "shared" (default): All workers share cookies from a master cookies file.
          First run: login in browser, cookies saved to ~/.nodriver-kit/cookies.dat
          Subsequent runs: cookies loaded into each worker.
        - "per_worker": Each worker has independent persistent cookies file.
          Worker 0 uses ~/.nodriver-kit/cookies/cookies_worker_0.dat, etc.
          Useful for multi-account scenarios.
        - "temp": No cookie persistence. Fresh state each run.

    Cookie persistence:
        Uses nodriver's browser.cookies.save()/load() API for reliable persistence.
        Client classes must accept 'cookies_file' parameter and handle loading/saving.

    Args:
        client_class: Browser client class (must support async context manager)
        workers: Number of workers to start (default: 3)
        max_retries: Max retries per job. -1 = unlimited (default: 2)
        state_file: Path to state file for persistence. None = no persistence.
        headless: Run Chrome in headless mode (default: False)
        close_browsers: Terminate Chrome on pool exit (default: True)
        fail_condition: Callable that returns True if job should be retried
        requeue_position: Where to put failed jobs: "front" or "back"
        profile: Profile mode - "shared", "per_worker", or "temp" (default: "shared")
        cookies_file: Path to shared cookies file (default: ~/.nodriver-kit/cookies.dat)
        cookies_dir: Base directory for per-worker cookies (default: ~/.nodriver-kit/cookies)
        profile_prefix: Prefix for temp Chrome profiles (only used in temp mode)
        **client_kwargs: Additional keyword arguments passed to client constructor
    """

    def __init__(
        self,
        client_class: type[ClientT],
        workers: int = 3,
        max_retries: int = 2,
        state_file: Path | str | None = None,
        headless: bool = False,
        close_browsers: bool = True,
        fail_condition: Callable[[dict], bool] | None = None,
        requeue_position: Literal["front", "back"] = "back",
        profile: ProfileMode = "shared",
        cookies_file: str | Path | None = None,
        cookies_dir: str | Path | None = None,
        profile_prefix: str = "nodriver_chrome_",
        **client_kwargs,
    ):
        self._client_class = client_class
        self._client_kwargs = client_kwargs
        self._num_workers = workers
        self._state_file = Path(state_file) if state_file else None
        self._max_retries = max_retries
        self._headless = headless
        self._close_browsers = close_browsers
        self._fail_condition = fail_condition
        self._requeue_position = requeue_position
        self._profile_prefix = profile_prefix

        # Profile management (uses cookies files for reliable persistence)
        self._profile_manager = ProfileManager(
            mode=profile,
            cookies_file=cookies_file,
            cookies_dir=cookies_dir,
        )

        # Worker management
        self._workers: dict[int, Worker] = {}
        self._worker_tasks: dict[int, asyncio.Task] = {}
        self._next_worker_id = 0
        self._used_ports: set[int] = set()

        # Job management - two queues for priority support
        self._job_queue: asyncio.Queue[Job] = asyncio.Queue()
        self._priority_queue: asyncio.Queue[Job] = asyncio.Queue()
        self._results: dict[str, JobResult] = {}
        self._pending_jobs: dict[str, Job] = {}
        self._result_events: dict[str, asyncio.Event] = {}

        # Pool state
        self._running = False
        self._state = PoolState()

        # Shared target tracking
        self._shared_targets: dict[str, _SharedTarget] = {}

        # Held jobs waiting for release
        self._held_jobs: dict[str, Job] = {}
        self._held_jobs_lock = asyncio.Lock()

        # Track jobs in selection phase (for timeout handling)
        self._jobs_in_selection: set[str] = set()

    async def __aenter__(self) -> "BrowserPool[ClientT]":
        """Start the pool and all workers."""
        # Load state if state file exists
        if self._state_file:
            loaded = load_state(self._state_file)
            if loaded:
                self._state = loaded
                self._results = loaded.completed.copy()
                # Re-queue pending and in-progress jobs
                for job in loaded.pending + loaded.in_progress:
                    job.status = JobStatus.PENDING
                    self._pending_jobs[job.job_id] = job
                    await self._job_queue.put(job)
                logger.info(
                    f"Loaded state: {len(self._results)} completed, "
                    f"{len(self._pending_jobs)} pending"
                )

        self._running = True

        # Start initial workers
        for _ in range(self._num_workers):
            await self.add_worker()

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Gracefully shutdown all workers."""
        self._running = False

        # Signal all workers to stop
        for worker in self._workers.values():
            worker.mark_stopping()

        # Cancel all worker tasks
        if self._worker_tasks:
            for task in self._worker_tasks.values():
                task.cancel()
            await asyncio.gather(*self._worker_tasks.values(), return_exceptions=True)

        # Close all browser clients and optionally terminate Chrome
        for worker in self._workers.values():
            if worker.client:
                try:
                    await worker.client.__aexit__(None, None, None)

                    if self._close_browsers and hasattr(worker.client, "_chrome_process"):
                        chrome_process = worker.client._chrome_process
                        if chrome_process is not None:
                            actual_pid = get_pid_on_port(worker.port)
                            if actual_pid:
                                logger.info(f"Killing Chrome (PID: {actual_pid}) for worker {worker.worker_id}")
                                kill_process_tree(actual_pid)
                except Exception as e:
                    logger.warning(f"Error closing worker {worker.worker_id}: {e}")

        # Final state save
        self.save_state()

    # =========================================================================
    # Worker Management
    # =========================================================================

    async def add_worker(self) -> int:
        """
        Add a new worker to the pool.

        Returns:
            worker_id of the new worker

        Example:
            new_id = await pool.add_worker()
            print(f"Added worker {new_id}")
        """
        worker_id = self._next_worker_id
        self._next_worker_id += 1

        # Get next available port
        port = get_available_port(exclude=self._used_ports, profile_prefix=self._profile_prefix)
        self._used_ports.add(port)

        # Create worker
        worker = Worker(worker_id=worker_id, port=port)
        self._workers[worker_id] = worker

        # Build client kwargs
        client_kwargs = dict(self._client_kwargs)
        client_kwargs["port"] = port
        client_kwargs["headless"] = self._headless

        # Add cookies_file from profile manager
        cookies_file = self._profile_manager.get_cookies_file(worker_id)
        if cookies_file is not None:
            client_kwargs["cookies_file"] = cookies_file

        # Initialize browser client
        client = self._client_class(**client_kwargs)

        try:
            await client.__aenter__()
            worker.client = client

            logger.info(f"Worker {worker_id} started on port {port}")
        except Exception as e:
            logger.error(f"Failed to start worker {worker_id}: {e}")
            worker.status = WorkerStatus.ERROR
            self._used_ports.discard(port)
            del self._workers[worker_id]
            raise

        # Start worker loop
        task = asyncio.create_task(self._worker_loop(worker))
        self._worker_tasks[worker_id] = task

        return worker_id

    async def remove_worker(self, worker_id: int, wait: bool = True) -> None:
        """
        Remove a worker from the pool.

        Args:
            worker_id: ID of the worker to remove
            wait: If True, wait for current task to complete before stopping
        """
        if worker_id not in self._workers:
            raise ValueError(f"Worker {worker_id} not found")

        worker = self._workers[worker_id]
        worker.mark_stopping()

        if wait and worker.status == WorkerStatus.BUSY:
            logger.info(f"Waiting for worker {worker_id} to finish current task...")
            await worker.wait_current_task()

        # Cancel worker task
        if worker_id in self._worker_tasks:
            self._worker_tasks[worker_id].cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_tasks[worker_id]
            del self._worker_tasks[worker_id]

        # Close browser client
        if worker.client:
            try:
                await worker.client.__aexit__(None, None, None)

                if self._close_browsers and hasattr(worker.client, "_chrome_process"):
                    chrome_process = worker.client._chrome_process
                    if chrome_process is not None:
                        actual_pid = get_pid_on_port(worker.port)
                        if actual_pid:
                            logger.info(f"Killing Chrome (PID: {actual_pid}) for worker {worker_id}")
                            kill_process_tree(actual_pid)
            except Exception as e:
                logger.warning(f"Error closing worker {worker_id}: {e}")

        port = worker.port
        self._used_ports.discard(port)

        worker.mark_stopped()
        del self._workers[worker_id]
        logger.info(f"Worker {worker_id} removed (port {port} released)")

    # =========================================================================
    # Job Management - AI-Friendly API
    # =========================================================================

    async def run(
        self,
        task_type: str,
        *args,
        max_retries: int | None = None,
        _hold: bool = False,
        **kwargs,
    ) -> str:
        """
        Run a task on the pool.

        This is the main API for submitting work. The task_type maps directly
        to a method name on your client class.

        Args:
            task_type: Method name to call on the client (e.g., "fetch", "scrape")
            *args: Positional arguments for the method
            max_retries: Max retries for this job. None = use pool default.
            _hold: If True, job waits until wait() is called. Use for batch setup.
            **kwargs: Keyword arguments for the method

        Returns:
            job_id for tracking this task

        Example:
            job_id = await pool.run("fetch", "https://example.com")
            job_id = await pool.run("scrape", url="https://example.com", depth=2)
        """
        job = Job(
            task_type=task_type,
            args=args,
            kwargs=kwargs,
            max_retries=max_retries if max_retries is not None else self._max_retries,
        )

        self._pending_jobs[job.job_id] = job
        self._result_events[job.job_id] = asyncio.Event()

        if _hold:
            async with self._held_jobs_lock:
                self._held_jobs[job.job_id] = job
            logger.debug(f"Submitted job {job.job_id}: {task_type} (held)")
        else:
            await self._job_queue.put(job)
            logger.debug(f"Submitted job {job.job_id}: {task_type}")

        return job.job_id

    # Alias for backward compatibility
    submit = run

    async def submit_batch(
        self,
        jobs: list[tuple[str, tuple, dict]],
    ) -> list[str]:
        """
        Submit multiple jobs at once.

        Args:
            jobs: List of (task_type, args, kwargs) tuples

        Returns:
            List of job_ids

        Example:
            urls = ["https://a.com", "https://b.com", "https://c.com"]
            job_ids = await pool.submit_batch([
                ("fetch", (url,), {}) for url in urls
            ])
        """
        job_ids = []
        for task_type, args, kwargs in jobs:
            job_id = await self.run(task_type, *args, **kwargs)
            job_ids.append(job_id)
        return job_ids

    def get_result(self, job_id: str) -> JobResult | None:
        """Get result for a completed job. Returns None if still pending."""
        return self._results.get(job_id)

    async def wait_for(self, job_id: str, timeout: float | None = None) -> JobResult:
        """
        Wait for a specific job to complete.

        Args:
            job_id: ID of the job to wait for
            timeout: Max seconds to wait. None = wait forever.

        Returns:
            JobResult when the job completes

        Raises:
            asyncio.TimeoutError: If timeout exceeded
            KeyError: If job_id not found
        """
        if job_id in self._results:
            return self._results[job_id]

        if job_id not in self._result_events:
            raise KeyError(f"Job {job_id} not found")

        await asyncio.wait_for(self._result_events[job_id].wait(), timeout=timeout)
        return self._results[job_id]

    async def wait(
        self,
        job_ids: list[str] | None = None,
        min_success: int | None = None,
        timeout: float | None = None,
    ) -> dict[str, JobResult]:
        """
        Wait for jobs to complete.

        Flexible wait method supporting multiple modes:
        - wait() - wait for ALL jobs to complete
        - wait(job_ids=[...]) - wait for specific jobs
        - wait(job_ids=[...], min_success=10) - shared target across jobs

        Args:
            job_ids: List of job IDs to monitor. None = wait for all.
            min_success: Shared success target across all specified jobs.
            timeout: Max seconds to wait. None = wait forever.

        Returns:
            Dict of job_id -> JobResult for completed jobs

        Example:
            # Wait for all
            results = await pool.wait()

            # Wait for specific jobs
            results = await pool.wait(job_ids=[job1, job2])

            # Shared target: stop when combined success reaches 10
            results = await pool.wait(job_ids=[job1, job2, job3], min_success=10)
        """
        if min_success is not None and job_ids is None:
            raise ValueError("min_success requires job_ids to be specified")

        # Setup shared target
        if min_success is not None and job_ids:
            shared = _SharedTarget(target=min_success)
            for job_id in job_ids:
                self._shared_targets[job_id] = shared
            logger.info(f"[wait] Setup shared target: {min_success} across {len(job_ids)} jobs")

        # Release held jobs
        async with self._held_jobs_lock:
            released_count = len(self._held_jobs)
            for job_id in list(self._held_jobs.keys()):
                job = self._held_jobs.pop(job_id)
                await self._job_queue.put(job)
                logger.debug(f"Released held job {job_id}: {job.task_type}")
            if released_count > 0:
                logger.info(f"[wait] Released {released_count} held jobs")

        start_time = asyncio.get_event_loop().time()

        # Mode 1: Wait for all jobs
        if job_ids is None:
            while True:
                queues_empty = self._job_queue.empty() and self._priority_queue.empty()
                if not self._pending_jobs and queues_empty:
                    all_idle = all(w.status == WorkerStatus.IDLE for w in self._workers.values())
                    if all_idle:
                        break

                if timeout is not None:
                    elapsed = asyncio.get_event_loop().time() - start_time
                    if elapsed >= timeout:
                        raise asyncio.TimeoutError("Timeout waiting for all jobs")

                await asyncio.sleep(0.5)

            return self._results.copy()

        # Mode 2 & 3: Wait for specific jobs
        completed_jobs: dict[str, JobResult] = {}
        total_success = 0
        pending_ids = set(job_ids)

        while pending_ids:
            for job_id in list(pending_ids):
                if job_id in self._results:
                    result = self._results[job_id]
                    completed_jobs[job_id] = result
                    pending_ids.remove(job_id)

                    if min_success is not None and result.success and result.data:
                        success_count = result.data.get("success_count", 0)
                        total_success += success_count
                        logger.info(
                            f"[wait] Job {job_id[:8]}... completed: "
                            f"+{success_count} success, total={total_success}/{min_success}"
                        )

                        if total_success >= min_success:
                            logger.info(
                                f"[wait] Target reached! {total_success}/{min_success} success"
                            )
                            # Wait for jobs in selection phase
                            if self._jobs_in_selection:
                                logger.info(f"[wait] Waiting for {len(self._jobs_in_selection)} jobs in selection...")
                                while self._jobs_in_selection:
                                    for jid in list(pending_ids):
                                        if jid in self._results:
                                            completed_jobs[jid] = self._results[jid]
                                            pending_ids.remove(jid)
                                    await asyncio.sleep(0.5)
                            return completed_jobs

            if not pending_ids:
                break

            # Check timeout (skip if jobs in selection)
            if timeout is not None and not self._jobs_in_selection:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= timeout:
                    if min_success is not None:
                        raise asyncio.TimeoutError(
                            f"Timeout. Got {total_success}/{min_success} success."
                        )
                    raise asyncio.TimeoutError("Timeout waiting for jobs")

            await asyncio.sleep(0.5)

        return completed_jobs

    # =========================================================================
    # State Management
    # =========================================================================

    def save_state(self) -> None:
        """Save current state to file."""
        if self._state_file is None:
            return

        self._state_file.parent.mkdir(parents=True, exist_ok=True)

        pending = list(self._pending_jobs.values())
        in_progress = [w.current_job for w in self._workers.values() if w.current_job]

        self._state.completed = self._results.copy()
        self._state.pending = pending
        self._state.in_progress = in_progress

        save_state(self._state, self._state_file)
        logger.debug(f"State saved: {len(self._results)} completed, {len(pending)} pending")

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def pending_count(self) -> int:
        """Number of pending jobs."""
        return len(self._pending_jobs) + self._job_queue.qsize() + self._priority_queue.qsize()

    @property
    def completed_count(self) -> int:
        """Number of completed jobs."""
        return len(self._results)

    @property
    def worker_count(self) -> int:
        """Number of active workers."""
        return len(self._workers)

    @property
    def worker_stats(self) -> dict[int, WorkerStats]:
        """Get statistics for all workers."""
        return {w_id: w.stats for w_id, w in self._workers.items()}

    def get_status(self) -> dict[str, Any]:
        """Get full status of the pool."""
        return {
            "running": self._running,
            "workers": {w_id: w.to_dict() for w_id, w in self._workers.items()},
            "pending_jobs": len(self._pending_jobs),
            "queue_size": self._job_queue.qsize(),
            "priority_queue_size": self._priority_queue.qsize(),
            "completed_jobs": len(self._results),
            "success_count": sum(1 for r in self._results.values() if r.success),
            "fail_count": sum(1 for r in self._results.values() if not r.success),
        }

    # =========================================================================
    # Internal Methods
    # =========================================================================

    async def _worker_loop(self, worker: Worker) -> None:
        """Main loop for a worker - pulls jobs and executes them."""
        while self._running and worker.status != WorkerStatus.STOPPING:
            try:
                # Try priority queue first, then regular queue
                job = None
                with contextlib.suppress(asyncio.QueueEmpty):
                    job = self._priority_queue.get_nowait()

                if job is None:
                    try:
                        job = await asyncio.wait_for(self._job_queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue

                # Execute the job
                worker.mark_busy(job)
                job.status = JobStatus.IN_PROGRESS

                try:
                    import time

                    start_time = time.time()
                    result_data, business_success = await self._execute_job(worker, job)
                    elapsed = time.time() - start_time

                    # Check fail_condition
                    if self._fail_condition and self._fail_condition(result_data):
                        await self._handle_job_failure(
                            worker, job, f"fail_condition returned True: {result_data}"
                        )
                    else:
                        result = JobResult(
                            job_id=job.job_id,
                            success=business_success,
                            data=result_data,
                            worker_id=worker.worker_id,
                        )
                        self._results[job.job_id] = result
                        worker.stats.success += 1
                        worker.stats.total_time += elapsed

                        self._pending_jobs.pop(job.job_id, None)
                        job.status = JobStatus.COMPLETED

                        if job.job_id in self._result_events:
                            self._result_events[job.job_id].set()

                        logger.info(
                            f"Worker {worker.worker_id} completed {job.task_type} "
                            f"({job.job_id[:8]}...) in {elapsed:.1f}s"
                        )

                except Exception as e:
                    await self._handle_job_failure(worker, job, str(e))

                finally:
                    worker.mark_idle()
                    self.save_state()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker.worker_id} loop error: {e}")
                await asyncio.sleep(1)

    async def _handle_job_failure(self, worker: Worker, job: Job, error: str) -> None:
        """Handle job failure - retry or mark as failed."""
        job.retries += 1
        worker.stats.fail += 1

        if job.max_retries == -1 or job.retries < job.max_retries:
            job.status = JobStatus.PENDING
            if self._requeue_position == "front":
                await self._priority_queue.put(job)
            else:
                await self._job_queue.put(job)
            logger.warning(
                f"Worker {worker.worker_id} failed {job.task_type} "
                f"({job.job_id[:8]}...), retry {job.retries}: {error}"
            )
        else:
            result = JobResult(
                job_id=job.job_id,
                success=False,
                error=error,
                worker_id=worker.worker_id,
            )
            self._results[job.job_id] = result
            self._pending_jobs.pop(job.job_id, None)
            job.status = JobStatus.FAILED

            if job.job_id in self._result_events:
                self._result_events[job.job_id].set()

            logger.error(
                f"Worker {worker.worker_id} failed {job.task_type} "
                f"({job.job_id[:8]}...) after {job.retries} retries: {error}"
            )

    def _make_shared_progress_callback(
        self,
        job_id: str,
        shared_state: dict[str, int],
        target: int,
    ) -> Callable[[int], Awaitable[bool]]:
        """Create progress callback for shared target mode."""

        async def callback(current_success: int) -> bool:
            shared_state[job_id] = current_success
            total = sum(shared_state.values())
            should_continue = total < target
            if not should_continue:
                logger.info(f"[shared_target] Total {total} >= {target}, signaling stop")
            return should_continue

        return callback

    def _wrap_selector(
        self,
        job_id: str,
        original_selector: Callable,
    ) -> Callable:
        """Wrap thumbnail_selector to track selection phase."""

        async def wrapped_selector(item_count: int, scan_favorites) -> list[int]:
            self._jobs_in_selection.add(job_id)
            logger.info(f"[selection] Job {job_id[:8]}... entering selection phase")
            try:
                return await original_selector(item_count, scan_favorites)
            finally:
                self._jobs_in_selection.discard(job_id)
                logger.info(f"[selection] Job {job_id[:8]}... exited selection phase")

        return wrapped_selector

    def _serialize_result(self, result: Any) -> Any:
        """Convert result to JSON-serializable format."""
        # Pydantic models
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="python", exclude_none=True, exclude_unset=False)

        # List of results
        if isinstance(result, list):
            return [self._serialize_result(item) for item in result]

        # Already serializable
        if isinstance(result, dict | str | int | float | bool | type(None)):
            return result

        # Objects with to_dict()
        if hasattr(result, "to_dict") and callable(result.to_dict):
            return result.to_dict()

        # Fallback: convert __dict__
        if hasattr(result, "__dict__"):
            return {k: v for k, v in result.__dict__.items() if not k.startswith("_")}

        return result

    async def _execute_job(self, worker: Worker, job: Job) -> tuple[Any, bool]:
        """Execute a job by dynamically calling the client method."""
        client = worker.client
        if client is None:
            raise RuntimeError(f"Worker {worker.worker_id} has no client")

        kwargs = dict(job.kwargs)

        # Extract ui_delay if present
        ui_delay = kwargs.pop("ui_delay", None)
        if ui_delay is not None and hasattr(client, "_ui_delay"):
            original_ui_delay = client._ui_delay
            client._ui_delay = ui_delay

        try:
            # Dynamic method lookup
            try:
                method = getattr(client, job.task_type)
            except AttributeError:
                available = [
                    m
                    for m in dir(client)
                    if not m.startswith("_") and callable(getattr(client, m, None))
                ]
                raise ValueError(
                    f"Unknown task_type: '{job.task_type}'. "
                    f"Available methods: {', '.join(sorted(available)[:20])}..."
                ) from None

            if not callable(method):
                raise ValueError(f"task_type '{job.task_type}' is not callable")

            # Inject progress_callback for shared target mode
            shared_target = self._shared_targets.get(job.job_id)
            if shared_target is not None:
                sig = inspect.signature(method)
                if "progress_callback" in sig.parameters:
                    kwargs["progress_callback"] = self._make_shared_progress_callback(
                        job.job_id, shared_target.state, shared_target.target
                    )
                    if "min_success" in sig.parameters and "min_success" not in kwargs:
                        kwargs["min_success"] = shared_target.target

            # Wrap thumbnail_selector
            original_selector = kwargs.get("thumbnail_selector")
            if original_selector is not None:
                kwargs["thumbnail_selector"] = self._wrap_selector(job.job_id, original_selector)

            # Call the method
            result = await method(*job.args, **kwargs)

            # Check business-level success
            if hasattr(result, "success") and isinstance(result.success, bool):
                business_success = result.success
            else:
                business_success = True

            return self._serialize_result(result), business_success

        finally:
            if ui_delay is not None and hasattr(client, "_ui_delay"):
                client._ui_delay = original_ui_delay
