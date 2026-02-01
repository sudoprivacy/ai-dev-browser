"""Save browser cookies to file."""

from ai_dev_browser.core import save_cookies

from .._cli import as_cli, wrap_core


cookies_save = as_cli()(wrap_core(save_cookies, "saved"))

if __name__ == "__main__":
    cookies_save.cli_main()
