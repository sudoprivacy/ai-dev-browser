"""Wait for page to be ready."""

from ai_dev_browser.core import wait_for_page

from .._cli import as_cli, wrap_core


page_wait = as_cli()(wrap_core(wait_for_page, "ready"))

if __name__ == "__main__":
    page_wait.cli_main()
