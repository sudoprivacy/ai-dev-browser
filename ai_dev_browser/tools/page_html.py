"""Get page HTML."""

from ai_dev_browser.core import get_page_html

from .._cli import as_cli, wrap_core


page_html = as_cli()(wrap_core(get_page_html, "html"))

if __name__ == "__main__":
    page_html.cli_main()
