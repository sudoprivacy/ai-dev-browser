"""Start a browser instance."""

from ai_dev_browser.core import start_browser

from .._cli import as_cli, wrap_core_sync


browser_start = as_cli(requires_tab=False)(wrap_core_sync(start_browser, "port"))

if __name__ == "__main__":
    browser_start.cli_main()
