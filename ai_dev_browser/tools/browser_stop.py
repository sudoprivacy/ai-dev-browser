"""Stop browser instance(s)."""

from ai_dev_browser.core import stop_browser

from .._cli import as_cli, wrap_core_sync


browser_stop = as_cli(requires_tab=False)(wrap_core_sync(stop_browser, "stopped"))

if __name__ == "__main__":
    browser_stop.cli_main()
