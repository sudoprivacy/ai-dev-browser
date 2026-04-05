"""AUTO-GENERATED from ai_dev_browser.core — cf_verify
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import cf_verify as _core_func

from .._cli import as_cli, wrap_core


cf_verify = as_cli()(wrap_core(_core_func, "verified"))

if __name__ == "__main__":
    cf_verify.cli_main()
