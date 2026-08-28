"""AUTO-GENERATED from ai_dev_browser.core — cookies_extract_live
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import cookies_extract_live as _core_func

from .._cli import as_cli, wrap_core


cookies_extract_live = as_cli()(wrap_core(_core_func, "cookies"))

if __name__ == "__main__":
    cookies_extract_live.cli_main()
