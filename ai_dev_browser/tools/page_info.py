"""Get page info."""

from ai_dev_browser.core import get_page_info

from .._cli import as_cli, wrap_core


page_info = as_cli()(wrap_core(get_page_info, "info"))

if __name__ == "__main__":
    page_info.cli_main()
