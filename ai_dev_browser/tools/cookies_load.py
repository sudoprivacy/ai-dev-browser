"""AUTO-GENERATED from ai_dev_browser.core.cookies.load_cookies
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.cookies import load_cookies as _core_func

from .._cli import as_cli, wrap_core


cookies_load = as_cli()(wrap_core(_core_func, "loaded"))

if __name__ == "__main__":
    cookies_load.cli_main()
