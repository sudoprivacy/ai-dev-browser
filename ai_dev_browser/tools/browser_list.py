"""List running browser instances."""

from ai_dev_browser.core import (
    find_our_chromes,
    find_ai_dev_browser_chromes,
    get_session_id,
    get_pid_on_port,
    is_chrome_in_use,
)
from .._cli import as_cli


@as_cli(requires_tab=False)
def browser_list(mine: bool = False) -> dict:
    """List running ai-dev-browser Chrome instances.

    Args:
        mine: If True, only show Chromes from this session
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

        all_ports = find_ai_dev_browser_chromes()
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


if __name__ == "__main__":
    browser_list.cli_main()
