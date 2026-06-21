"""AUTO-GENERATED from ai_dev_browser.core — cookies_extract
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import cookies_extract as _core_func

from .._cli import as_cli, wrap_core_sync


cookies_extract = as_cli(requires_tab=False)(wrap_core_sync(_core_func, "cookies"))

if __name__ == "__main__":
    cookies_extract.cli_main()
