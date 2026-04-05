"""AUTO-GENERATED from ai_dev_browser.core — dialog_respond
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import dialog_respond as _core_func

from .._cli import as_cli, wrap_core


dialog_respond = as_cli()(wrap_core(_core_func, "handled"))

if __name__ == "__main__":
    dialog_respond.cli_main()
