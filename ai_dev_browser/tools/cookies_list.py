"""List browser cookies."""

from ai_dev_browser.core import list_cookies

from .._cli import as_cli, wrap_core


cookies_list = as_cli()(wrap_core(list_cookies, "cookies"))

if __name__ == "__main__":
    cookies_list.cli_main()
