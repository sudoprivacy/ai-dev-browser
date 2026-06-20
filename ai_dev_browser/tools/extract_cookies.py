"""AUTO-GENERATED from ai_dev_browser.core — extract_cookies
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import extract_cookies as _core_func

from .._cli import as_cli, wrap_core_sync


extract_cookies = as_cli(requires_tab=False)(wrap_core_sync(_core_func, "cookies"))

if __name__ == "__main__":
    extract_cookies.cli_main()
