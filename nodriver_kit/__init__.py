"""nodriver-kit: Browser automation toolkit built on nodriver.

AI-first design for intuitive browser automation.

Modules:
    browser: Chrome detection, launching, and port management
    pool: Parallel task execution with multiple browser workers

Quick Start:
    # Simple browser launch
    from nodriver_kit import find_chrome, launch_chrome, get_available_port

    port = get_available_port()
    process = launch_chrome(port=port)

    # Worker pool for parallel tasks
    from nodriver_kit import BrowserPool

    async with BrowserPool(MyClient, workers=3) as pool:
        await pool.run("fetch", "https://example.com")
        results = await pool.wait()

For Cloudflare bypass, use nodriver's built-in tab.verify_cf():
    import nodriver as uc

    browser = await uc.start()
    tab = await browser.get("https://protected-site.com")
    await tab.verify_cf()  # Built-in CF bypass
"""

# Browser management
from .browser import (
    # Chrome detection and launching
    find_chrome,
    launch_chrome,
    DEFAULT_PROFILE_PREFIX,
    # Port management
    is_port_in_use,
    is_temp_chrome_on_port,
    is_chrome_in_use,
    find_temp_chromes,
    get_available_port,
    DEFAULT_DEBUG_PORT,
    DEFAULT_DEBUG_HOST,
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

__version__ = "0.1.0"

__all__ = [
    # Version
    "__version__",
    # Browser management
    "find_chrome",
    "launch_chrome",
    "DEFAULT_PROFILE_PREFIX",
    "is_port_in_use",
    "is_temp_chrome_on_port",
    "is_chrome_in_use",
    "find_temp_chromes",
    "get_available_port",
    "DEFAULT_DEBUG_PORT",
    "DEFAULT_DEBUG_HOST",
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
]
