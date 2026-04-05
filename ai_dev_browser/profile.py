"""Profile management for browser pools.

Provides three profile modes for parallel browser scenarios:

1. "shared" - All workers share cookies from a master cookies file
2. "per_worker" - Each worker has independent persistent cookies file
3. "temp" - No cookie persistence (fresh state each run)

Uses cookies.save()/load() API for reliable cookie persistence.

Example:
    from ai_dev_browser import BrowserPool

    # Shared mode (default) - all workers share login state from master cookies file
    async with BrowserPool(MyClient, profile="shared") as pool:
        ...

    # Per-worker mode - each worker has independent persistent login
    async with BrowserPool(MyClient, profile="per_worker") as pool:
        ...

    # Temp mode - no cookie persistence
    async with BrowserPool(MyClient, profile="temp") as pool:
        ...
"""

import logging
from pathlib import Path
from typing import Literal

from .core.config import DEFAULT_COOKIES_DIR, DEFAULT_COOKIES_FILE


logger = logging.getLogger(__name__)

ProfileMode = Literal["shared", "per_worker", "temp"]


class ProfileManager:
    """
    Manages cookies files for BrowserPool workers.

    Manages cookie persistence for browser pool workers.
    All workers use temporary profiles and share authentication state via cookies files.

    Three modes:
    - shared: All workers load from the same cookies.dat file
    - per_worker: Each worker has its own cookies_worker_N.dat file
    - temp: No cookie persistence (fresh state each run)

    Args:
        mode: Profile mode - "shared", "per_worker", or "temp"
        cookies_file: Path to shared cookies file (for shared mode)
        cookies_dir: Base directory for per-worker cookies files
    """

    def __init__(
        self,
        mode: ProfileMode = "shared",
        cookies_file: str | Path | None = None,
        cookies_dir: str | Path | None = None,
    ):
        self.mode = mode
        self.cookies_file = Path(cookies_file or DEFAULT_COOKIES_FILE).expanduser()
        self.cookies_dir = Path(cookies_dir or DEFAULT_COOKIES_DIR).expanduser()

        # Ensure directories exist
        if mode == "shared":
            self.cookies_file.parent.mkdir(parents=True, exist_ok=True)
        elif mode == "per_worker":
            self.cookies_dir.mkdir(parents=True, exist_ok=True)

    def get_cookies_file(self, worker_id: int) -> Path | None:
        """
        Get the cookies file path for a worker.

        Args:
            worker_id: The worker's ID

        Returns:
            Path to cookies file, or None for temp mode
        """
        if self.mode == "temp":
            return None

        if self.mode == "shared":
            # All workers share the same cookies file
            if self.cookies_file.exists():
                logger.debug(
                    f"Worker {worker_id} using shared cookies: {self.cookies_file}"
                )
            else:
                logger.warning(
                    f"Worker {worker_id}: shared cookies file not found at {self.cookies_file}. "
                    f"Login in browser to create cookies."
                )
            return self.cookies_file

        if self.mode == "per_worker":
            # Each worker has its own cookies file
            worker_cookies = self.cookies_dir / f"cookies_worker_{worker_id}.dat"
            logger.debug(
                f"Worker {worker_id} using persistent cookies: {worker_cookies}"
            )
            return worker_cookies

        return None
