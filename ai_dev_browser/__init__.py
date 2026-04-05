"""ai-dev-browser: Browser automation toolkit with CDP WebSocket transport.

AI-first design for intuitive browser automation.

    from ai_dev_browser import cdp, connect_browser, browser_start
"""

# Core operations (all shared code lives here)
# Core browser operations (shared by tools/ and Python code)
from . import core
from .core import (
    # Config
    DEFAULT_BASE_DIR,
    DEFAULT_COOKIES_DIR,
    DEFAULT_COOKIES_FILE,
    DEFAULT_DEBUG_HOST,
    DEFAULT_DEBUG_PORT,
    DEFAULT_PORT_RANGE,
    DEFAULT_PROFILE_DIR,
    DEFAULT_PROFILE_PREFIX,
    # Chrome detection and launching
    find_chrome,
    find_debug_chromes,
    find_workspace_chromes,
    get_available_port,
    # Process management
    get_pid_on_port,
    get_process_cmdline,
    # Port management
    is_port_in_use,
    launch_chrome,
)

# Cloudflare verification
from .core.cloudflare import cloudflare_verify

# Worker pool
from .pool import (
    BrowserPool,
    Job,
    JobResult,
    JobStatus,
    PoolState,
    Worker,
    WorkerStats,
    WorkerStatus,
    load_state,
    save_state,
)

# Profile management
from .profile import ProfileManager, ProfileMode


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
    "find_debug_chromes",
    "find_workspace_chromes",
    "get_available_port",
    # Process
    "get_pid_on_port",
    "get_process_cmdline",
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
    "cloudflare_verify",
    # Core operations module
    "core",
    # CDP protocol access (vendored)
    "cdp",
    # Tools
    "browser_start",
    "browser_stop",
    "connect_browser",
]

# Vendored CDP protocol module
from . import cdp

from .core import connect_browser

# Core functions also available at package level
from .core import browser_start, browser_stop
