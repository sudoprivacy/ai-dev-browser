"""AUTO-GENERATED from ai_dev_browser.core.cookies.save_cookies
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.cookies import save_cookies as _core_func

from .._cli import as_cli, wrap_core


cookies_save = as_cli()(wrap_core(_core_func, "saved"))

if __name__ == "__main__":
    cookies_save.cli_main()
