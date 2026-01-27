"""Stop browser instance(s)."""

from ai_dev_browser.core import (
    find_our_chromes,
    kill_process_tree,
    cleanup_temp_profile,
    get_pid_on_port,
)
from ._cli import as_cli


@as_cli(requires_tab=False)
def browser_stop(port: int = None, stop_all: bool = False) -> dict:
    """Stop browser instance(s).

    Args:
        port: Port of browser to stop
        stop_all: Stop all our browser instances
    """
    try:
        if not port and not stop_all:
            return {"error": "Please specify --port or --stop-all"}

        stopped = []

        if stop_all:
            browsers = find_our_chromes()
            for browser in browsers:
                try:
                    kill_process_tree(browser["pid"])
                    if browser.get("profile_dir"):
                        cleanup_temp_profile(browser["profile_dir"])
                    stopped.append({"port": browser["port"], "pid": browser["pid"]})
                except Exception:
                    pass
        else:
            pid = get_pid_on_port(port)
            if pid:
                kill_process_tree(pid)
                stopped.append({"port": port, "pid": pid})

        return {
            "stopped": True,
            "count": len(stopped),
            "browsers": stopped,
        }
    except Exception as e:
        return {"error": f"Stop browser failed: {e}"}


if __name__ == "__main__":
    browser_stop.cli_main()
