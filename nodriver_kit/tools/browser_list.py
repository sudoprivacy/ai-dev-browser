"""List running browser instances.

CLI:
    python -m nodriver_kit.tools.browser_list              # Only this session (default)
    python -m nodriver_kit.tools.browser_list --all        # All nodriver-kit Chromes

Python:
    from nodriver_kit.tools import browser_list
    result = browser_list()                  # Only our session
    result = browser_list(all_sessions=True) # All nodriver-kit Chromes
"""

import argparse
import json
from nodriver_kit.core import (
    find_our_chromes,
    find_nodriver_kit_chromes,
    get_session_id,
    get_pid_on_port,
)


def browser_list(all_sessions: bool = False) -> dict:
    """List running nodriver-kit Chrome instances.

    Args:
        all_sessions: If True, list all nodriver-kit Chromes (from any session).
                      If False (default), only Chromes from this session.

    Returns:
        {"browsers": [...], "count": ..., "session_id": ...}

    Note:
        - Default shows only current session's Chromes (per-session visibility)
        - all_sessions=True shows all nodriver-kit Chromes (useful for reuse)
        - Neither mode shows user-started Chromes (use find_debug_chromes for that)
    """
    try:
        if all_sessions:
            # All nodriver-kit Chromes (any session, but not user-started)
            ports = find_nodriver_kit_chromes()
        else:
            # Only current session's Chromes
            ports = find_our_chromes(exclude_in_use=False)

        browsers = [(port, get_pid_on_port(port)) for port in ports]

        result = {
            "browsers": browsers,
            "count": len(browsers),
            "session_id": get_session_id(),
            "scope": "all_nodriver_kit" if all_sessions else "current_session",
        }
        return result
    except Exception as e:
        return {"error": f"List browsers failed: {e}"}


def cli_main():
    parser = argparse.ArgumentParser(description="List running browser instances")
    parser.add_argument(
        "--all", "-a", action="store_true",
        help="Show all nodriver-kit Chromes (from any session)"
    )
    args = parser.parse_args()

    result = browser_list(all_sessions=args.all)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    cli_main()
