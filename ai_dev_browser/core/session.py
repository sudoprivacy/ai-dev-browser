"""Session management for ai-dev-browser.

Each ai-dev-browser process gets a unique session ID, used to identify
browsers started by this process. This prevents accidentally connecting
to browsers started by other agents/scripts.

The session ID is passed to Chrome as a command line argument:
    --ai-dev-browser-session=<session_id>

This is invisible to websites (they cannot see process command line).
"""

import uuid


# Generate once per process import
SESSION_ID: str = str(uuid.uuid4())[:8]  # Short ID for readability

# Command line flag name
SESSION_FLAG = "--ai-dev-browser-session"


def get_session_id() -> str:
    """Get the current process's session ID."""
    return SESSION_ID


def make_session_arg() -> str:
    """Create the command line argument for Chrome."""
    return f"{SESSION_FLAG}={SESSION_ID}"


def extract_session_id(cmdline: str) -> str | None:
    """Extract session ID from a Chrome command line.

    Args:
        cmdline: Process command line string

    Returns:
        Session ID if found, None otherwise
    """
    if SESSION_FLAG not in cmdline:
        return None

    # Find the flag and extract value
    for part in cmdline.split():
        if part.startswith(f"{SESSION_FLAG}="):
            return part.split("=", 1)[1]

    return None


def is_our_session(cmdline: str) -> bool:
    """Check if a Chrome command line belongs to our session.

    Args:
        cmdline: Process command line string

    Returns:
        True if the Chrome was started by this process
    """
    return extract_session_id(cmdline) == SESSION_ID
