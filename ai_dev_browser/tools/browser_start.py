"""Start a browser instance."""

from pathlib import Path
from ai_dev_browser.core import (
    launch_chrome,
    get_available_port,
    find_our_chromes,
    find_ai_dev_browser_chromes,
    find_debug_chromes,
    is_chrome_in_use,
    get_pid_on_port,
    ReuseStrategy,
)
from ._cli import as_cli

DEFAULT_PROFILE_DIR = Path.home() / ".ai-dev-browser" / "profiles"


@as_cli(requires_tab=False)
def browser_start(
    port: int = None,
    headless: bool = False,
    url: str = None,
    profile: str = None,
    temp: bool = False,
    reuse: ReuseStrategy = "none",
) -> dict:
    """Start or reuse a browser instance.

    Args:
        port: Debug port (auto-assigned if None)
        headless: Run in headless mode
        url: Initial URL to open (default: about:blank)
        profile: Profile name (default: "default", stored in ~/.ai-dev-browser/profiles/)
        temp: Use temporary profile instead (clean, no persistence)
        reuse: Reuse strategy - none/this_session/ai_dev_browser/any
    """
    try:
        # Try to reuse existing Chrome based on reuse strategy
        if reuse != "none":
            reused_port = _find_reusable_chrome(reuse)
            if reused_port:
                pid = get_pid_on_port(reused_port)
                return {
                    "port": reused_port,
                    "pid": pid,
                    "reused": True,
                    "message": f"Reusing existing Chrome on port {reused_port}",
                }

        # No reusable Chrome found, start new one
        if port is None:
            # When reuse="none", don't let get_available_port() reuse either
            port = get_available_port(reuse=(reuse != "none"))

        # Determine user data directory
        if temp:
            user_data_dir = None  # launch_chrome will create temp dir
            profile_name = "(temp)"
        else:
            profile_name = profile or "default"
            user_data_dir = DEFAULT_PROFILE_DIR / profile_name
            user_data_dir.mkdir(parents=True, exist_ok=True)

        # Use launch_chrome which starts a subprocess that stays alive
        start_url = url or "about:blank"
        process = launch_chrome(
            port=port,
            headless=headless,
            start_url=start_url,
            user_data_dir=str(user_data_dir) if user_data_dir else None,
        )

        return {
            "port": port,
            "pid": process.pid,
            "headless": headless,
            "url": start_url,
            "profile": profile_name,
            "reused": False,
            "message": f"Browser started on port {port}",
        }
    except Exception as e:
        return {"error": f"Start browser failed: {e}"}


def _find_reusable_chrome(reuse: str) -> int | None:
    """Find a reusable Chrome based on reuse strategy.

    Args:
        reuse: "this_session", "ai_dev_browser", or "any"

    Returns:
        Port number if found, None otherwise
    """
    if reuse == "this_session":
        # Only current session's Chromes (returns list[int])
        for port in find_our_chromes(exclude_in_use=False):
            if not is_chrome_in_use(port):
                return port

    elif reuse == "ai_dev_browser":
        # Any ai-dev-browser Chrome (returns list[int])
        for port in find_ai_dev_browser_chromes():
            if not is_chrome_in_use(port):
                return port

    elif reuse == "any":
        # Any debugging Chrome (returns list[tuple[int, int]])
        for port, _pid in find_debug_chromes():
            if not is_chrome_in_use(port):
                return port

    return None


if __name__ == "__main__":
    browser_start.cli_main()
