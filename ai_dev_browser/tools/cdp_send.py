"""AUTO-GENERATED from ai_dev_browser.core — cdp_send
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import cdp_send as _core_func

from .._cli import as_cli, wrap_core


cdp_send = as_cli()(wrap_core(_core_func, "result"))

if __name__ == "__main__":
    cdp_send.cli_main()
