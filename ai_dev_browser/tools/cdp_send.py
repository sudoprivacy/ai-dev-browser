"""AUTO-GENERATED from ai_dev_browser.core.cdp.send_cdp_command
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.cdp import send_cdp_command as _core_func

from .._cli import as_cli, wrap_core


cdp_send = as_cli()(wrap_core(_core_func, "result"))

if __name__ == "__main__":
    cdp_send.cli_main()
