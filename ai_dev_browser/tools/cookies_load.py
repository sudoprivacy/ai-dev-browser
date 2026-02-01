"""Load cookies from file into browser."""

from ai_dev_browser.core import load_cookies

from .._cli import as_cli, wrap_core


cookies_load = as_cli()(wrap_core(load_cookies, "loaded"))

if __name__ == "__main__":
    cookies_load.cli_main()
