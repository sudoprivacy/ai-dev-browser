"""ai-dev-browser: Browser automation toolkit built on nodriver.

AI-first design for intuitive browser automation.

IMPORTANT: Always import from ai_dev_browser, not directly from nodriver.
    from ai_dev_browser import cdp, connect_browser, browser_start
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
    is_ai_dev_browser_chrome_on_port,
    is_chrome_in_use,
    find_our_chromes,
    find_ai_dev_browser_chromes,
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
    "is_ai_dev_browser_chrome_on_port",
    "is_chrome_in_use",
    "find_our_chromes",
    "find_ai_dev_browser_chromes",
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
    # Re-exported from nodriver (use these instead of importing nodriver directly)
    "cdp",
    # Tools
    "browser_start",
    "browser_stop",
    "connect_browser",
]

# Re-export nodriver.cdp for CDP protocol access
from nodriver import cdp

# Re-export commonly used tools as functions
from .tools.browser_start import browser_start
from .tools.browser_stop import browser_stop
from .core import connect_browser
