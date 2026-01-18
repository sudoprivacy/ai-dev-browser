"""List running browser instances.

CLI:
    python -m nodriver_kit.tools.browser_list              # All debug browsers
    python -m nodriver_kit.tools.browser_list --session    # Only this session

Python:
    from nodriver_kit.tools import browser_list
    result = browser_list()                  # Only our session (same process)
    result = browser_list(all_sessions=True) # All debug browsers
"""

import argparse
import json
from nodriver_kit.core import find_debug_chromes, find_our_chromes, get_session_id, get_pid_on_port


def browser_list(all_sessions: bool = False) -> dict:
    """List running debug Chrome instances.

    Args:
        all_sessions: If True, list all debug browsers.
                      If False (default), only browsers started by this Python process.

    Returns:
        {"browsers": [...], "count": ..., "session_id": ...}

    Note:
        Default (all_sessions=False) is useful in long-running Python processes
        like BrowserPool where you want to track browsers you started.
        For CLI usage, --session flag filters to current session but since each
        CLI invocation is a new process, this is mainly for debugging.
    """
    try:
        if all_sessions:
            browsers = find_debug_chromes()
        else:
            # find_our_chromes returns list of ports, convert to (port, pid) tuples
            ports = find_our_chromes(exclude_in_use=False)
            browsers = [(port, get_pid_on_port(port)) for port in ports]

        result = {
            "browsers": browsers,
            "count": len(browsers),
            "session_id": get_session_id(),
        }
        return result
    except Exception as e:
        return {"error": f"List browsers failed: {e}"}


def cli_main():
    parser = argparse.ArgumentParser(description="List running browser instances")
    parser.add_argument(
        "--session", "-s", action="store_true",
        help="Only show browsers from this session (each CLI call is a new session)"
    )
    args = parser.parse_args()

    # CLI defaults to all, since each invocation is a new process/session
    result = browser_list(all_sessions=not args.session)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    cli_main()
