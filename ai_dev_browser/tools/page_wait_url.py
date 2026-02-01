"""Wait for URL to match a pattern."""

from ai_dev_browser.core import wait_for_url_match

from .._cli import as_cli, wrap_core


page_wait_url = as_cli()(wrap_core(wait_for_url_match, "matched"))

if __name__ == "__main__":
    page_wait_url.cli_main()
