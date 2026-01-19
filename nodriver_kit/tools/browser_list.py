"""List running browser instances.

CLI:
    python -m nodriver_kit.tools.browser_list         # All nodriver-kit Chromes
    python -m nodriver_kit.tools.browser_list --mine  # Only this session

Python:
    from nodriver_kit.tools import browser_list
    result = browser_list()            # All nodriver-kit Chromes
    result = browser_list(mine=True)   # Only this session
"""

import argparse
import json
from nodriver_kit.core import (
    find_our_chromes,
    find_nodriver_kit_chromes,
    get_session_id,
    get_pid_on_port,
    is_chrome_in_use,
)


def browser_list(mine: bool = False) -> dict:
    """List running nodriver-kit Chrome instances.

    Args:
        mine: If True, only show Chromes from this session.
              If False (default), show all nodriver-kit Chromes.

    Returns:
        {"this_session": [...], "other_sessions": [...], "count": ...}
    """
    try:
        session_id = get_session_id()
        my_ports = set(find_our_chromes(exclude_in_use=False))

        if mine:
            browsers = []
            for p in my_ports:
                browsers.append({
                    "port": p,
                    "pid": get_pid_on_port(p),
                    "can_connect": not is_chrome_in_use(p),
                })
            return {"browsers": browsers, "count": len(my_ports)}

        all_ports = find_nodriver_kit_chromes()
        this_session = []
        other_sessions = []

        for p in all_ports:
            entry = {
                "port": p,
                "pid": get_pid_on_port(p),
                "can_connect": not is_chrome_in_use(p),
            }
            if p in my_ports:
                this_session.append(entry)
            else:
                other_sessions.append(entry)

        return {
            "this_session": this_session,
            "other_sessions": other_sessions,
            "count": len(all_ports),
        }
    except Exception as e:
        return {"error": f"List browsers failed: {e}"}


def cli_main():
    parser = argparse.ArgumentParser(description="List running browser instances")
    parser.add_argument(
        "--mine", "-m", action="store_true",
        help="Only show Chromes from this session"
    )
    args = parser.parse_args()

    result = browser_list(mine=args.mine)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    cli_main()
