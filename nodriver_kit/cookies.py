"""Cookie management for browser pools.

Provides two cookie persistence modes for parallel browser scenarios:

1. Cookies.shared(file) - All workers share the same cookies via file
2. Cookies.per_worker(dir) - Each worker has independent persistent profile

Example:
    from nodriver_kit import BrowserPool, Cookies

    # Shared cookies - all workers share login state
    async with BrowserPool(MyClient, cookies=Cookies.shared("session.dat")) as pool:
        ...

    # Per-worker cookies - each worker has independent login state
    async with BrowserPool(MyClient, cookies=Cookies.per_worker("~/.profiles/")) as pool:
        ...
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class CookieStrategy(ABC):
    """Base class for cookie management strategies."""

    @abstractmethod
    async def on_browser_start(self, browser: Any, worker_id: int) -> None:
        """Called after browser starts. Load cookies if needed."""
        pass

    @abstractmethod
    async def on_browser_stop(self, browser: Any, worker_id: int) -> None:
        """Called before browser stops. Save cookies if needed."""
        pass

    @abstractmethod
    def get_user_data_dir(self, worker_id: int) -> Path | None:
        """Return user_data_dir for this worker, or None for temp profile."""
        pass


def _get_browser(client: Any) -> Any | None:
    """Try to get nodriver browser from client via duck typing."""
    # Try common attribute names
    for attr in ("_browser", "browser", "_nodriver_browser"):
        browser = getattr(client, attr, None)
        if browser is not None and hasattr(browser, "cookies"):
            return browser
    return None


@dataclass
class SharedCookies(CookieStrategy):
    """
    All workers share cookies via a single file.

    How it works:
    - Each worker uses a temporary Chrome profile
    - On start: load cookies from shared file into browser
    - On stop: save cookies from browser to shared file
    - Last worker to exit saves the final cookie state

    Uses nodriver's native browser.cookies.save/load which uses pickle format.

    Requires:
        The client must expose a nodriver browser via `_browser` or `browser` attribute.

    Args:
        file: Path to cookie file (default: "cookies.dat")
        pattern: Regex pattern to filter cookies (default: ".*" for all)

    Example:
        pool = BrowserPool(MyClient, cookies=Cookies.shared("session.dat"))
    """

    file: str | Path = "cookies.dat"
    pattern: str = ".*"

    def __post_init__(self):
        self.file = Path(self.file).expanduser().resolve()

    async def on_browser_start(self, client: Any, worker_id: int) -> None:
        """Load shared cookies into browser."""
        browser = _get_browser(client)
        if browser is None:
            return

        if self.file.exists():
            try:
                await browser.cookies.load(str(self.file), pattern=self.pattern)
            except Exception:
                pass  # File might be corrupted or empty, ignore

    async def on_browser_stop(self, client: Any, worker_id: int) -> None:
        """Save cookies to shared file."""
        browser = _get_browser(client)
        if browser is None:
            return

        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            await browser.cookies.save(str(self.file), pattern=self.pattern)
        except Exception:
            pass  # Browser might already be closed

    def get_user_data_dir(self, worker_id: int) -> Path | None:
        """Shared cookies use temp profiles."""
        return None


@dataclass
class PerWorkerCookies(CookieStrategy):
    """
    Each worker has independent persistent cookies via separate profile directories.

    How it works:
    - Each worker gets a dedicated Chrome profile directory
    - Chrome manages cookies automatically (persisted in profile)
    - No manual save/load needed

    Requires:
        The client must accept `user_data_dir` parameter in its constructor.
        BrowserPool will pass get_user_data_dir() result to client.

    Args:
        directory: Base directory for profiles. Each worker gets a subdirectory.
                  e.g., "~/.profiles/" creates ~/.profiles/worker_0/, worker_1/, etc.

    Example:
        pool = BrowserPool(MyClient, cookies=Cookies.per_worker("~/.browser_profiles/"))
    """

    directory: str | Path = "~/.nodriver_profiles/"

    def __post_init__(self):
        self.directory = Path(self.directory).expanduser().resolve()

    async def on_browser_start(self, client: Any, worker_id: int) -> None:
        """No action needed - Chrome loads cookies from profile automatically."""
        pass

    async def on_browser_stop(self, client: Any, worker_id: int) -> None:
        """No action needed - Chrome saves cookies to profile automatically."""
        pass

    def get_user_data_dir(self, worker_id: int) -> Path | None:
        """Return dedicated profile directory for this worker."""
        profile_dir = self.directory / f"worker_{worker_id}"
        profile_dir.mkdir(parents=True, exist_ok=True)
        return profile_dir


class Cookies:
    """
    Factory for cookie management strategies.

    Two modes available:
    - Cookies.shared(file) - All workers share cookies via file
    - Cookies.per_worker(dir) - Each worker has independent profile

    Example:
        from nodriver_kit import BrowserPool, Cookies

        # All workers share login state
        pool = BrowserPool(MyClient, cookies=Cookies.shared("cookies.dat"))

        # Each worker has independent login state
        pool = BrowserPool(MyClient, cookies=Cookies.per_worker("~/.profiles/"))

        # No persistence (default) - temp profiles, cookies lost on exit
        pool = BrowserPool(MyClient)
    """

    @staticmethod
    def shared(file: str | Path = "cookies.dat", pattern: str = ".*") -> SharedCookies:
        """
        Create shared cookie strategy.

        All workers share the same cookies via a single file.
        Useful when all workers need the same login session.

        Args:
            file: Path to cookie file
            pattern: Regex to filter which cookies to save/load

        Returns:
            SharedCookies strategy
        """
        return SharedCookies(file=file, pattern=pattern)

    @staticmethod
    def per_worker(directory: str | Path = "~/.nodriver_profiles/") -> PerWorkerCookies:
        """
        Create per-worker cookie strategy.

        Each worker has independent persistent profile directory.
        Useful for multi-account scenarios.

        Args:
            directory: Base directory for worker profiles

        Returns:
            PerWorkerCookies strategy
        """
        return PerWorkerCookies(directory=directory)
