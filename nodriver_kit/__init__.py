"""nodriver-kit: Browser automation toolkit built on nodriver.

AI-first design for intuitive browser automation.

Modules:
    browser: Chrome detection, launching, and port management
    pool: Parallel task execution with multiple browser workers
    profile: Cookie file management for reliable persistence

Quick Start:
    # Worker pool with shared cookies (default)
    from nodriver_kit import BrowserPool

    async with BrowserPool(MyClient, workers=3) as pool:
        # First run: login in browser, cookies saved to ~/.nodriver-kit/cookies.dat
        # Subsequent runs: cookies auto-loaded into each worker
        await pool.run("fetch", "https://example.com")
        results = await pool.wait()

Profile modes:
    - "shared" (default): All workers share cookies from ~/.nodriver-kit/cookies.dat
    - "per_worker": Each worker has own cookies file in ~/.nodriver-kit/cookies/
    - "temp": No cookie persistence

Cookie persistence:
    Uses nodriver's browser.cookies.save()/load() API for reliable persistence.
    Client classes must accept 'cookies_file' parameter and handle loading/saving.

For Cloudflare bypass, use nodriver's built-in tab.verify_cf():
    import nodriver as uc

    browser = await uc.start()
    tab = await browser.get("https://protected-site.com")
    await tab.verify_cf()  # Built-in CF bypass
"""

# Core operations (all shared code lives here)
from .core import (
    # Config
    DEFAULT_BASE_DIR,
    DEFAULT_PROFILE_DIR,
    DEFAULT_COOKIES_FILE,
    DEFAULT_COOKIES_DIR,
    DEFAULT_PROFILE_PREFIX,
    DEFAULT_DEBUG_HOST,
    DEFAULT_DEBUG_PORT,
    DEFAULT_PORT_RANGE,
    # Chrome detection and launching
    find_chrome,
    launch_chrome,
    # Port management
    is_port_in_use,
    is_our_chrome_on_port,
    is_chrome_in_use,
    find_our_chromes,
    find_debug_chromes,
    get_available_port,
    cleanup_temp_profile,
    # Session management
    get_session_id,
    is_our_session,
    extract_session_id,
    # Process management
    get_pid_on_port,
    get_process_cmdline,
    kill_process_tree,
)

# Worker pool
from .pool import (
    BrowserPool,
    Job,
    JobResult,
    JobStatus,
    Worker,
    WorkerStats,
    WorkerStatus,
    PoolState,
    load_state,
    save_state,
)

# Profile management
from .profile import ProfileManager, ProfileMode

# Cloudflare verification (wraps nodriver's native verify_cf)
from .core.cloudflare import verify_cloudflare

# Core browser operations (shared by tools/ and Python code)
from . import core

__version__ = "0.1.0"

__all__ = [
    # Version
    "__version__",
    # Config
    "DEFAULT_BASE_DIR",
    "DEFAULT_PROFILE_DIR",
    "DEFAULT_COOKIES_FILE",
    "DEFAULT_COOKIES_DIR",
    "DEFAULT_PROFILE_PREFIX",
    "DEFAULT_DEBUG_HOST",
    "DEFAULT_DEBUG_PORT",
    "DEFAULT_PORT_RANGE",
    # Chrome
    "find_chrome",
    "launch_chrome",
    # Port
    "is_port_in_use",
    "is_our_chrome_on_port",
    "is_chrome_in_use",
    "find_our_chromes",
    "find_debug_chromes",
    "get_available_port",
    "cleanup_temp_profile",
    # Session
    "get_session_id",
    "is_our_session",
    "extract_session_id",
    # Process
    "get_pid_on_port",
    "get_process_cmdline",
    "kill_process_tree",
    # Worker pool
    "BrowserPool",
    "Job",
    "JobResult",
    "JobStatus",
    "Worker",
    "WorkerStats",
    "WorkerStatus",
    "PoolState",
    "load_state",
    "save_state",
    # Profile management
    "ProfileManager",
    "ProfileMode",
    # Cloudflare verification
    "verify_cloudflare",
    # Core operations module
    "core",
]
