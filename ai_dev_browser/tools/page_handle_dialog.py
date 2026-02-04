"""AUTO-GENERATED from ai_dev_browser.core.dialog.handle_dialog_action
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.dialog import handle_dialog_action as _core_func

from .._cli import as_cli, wrap_core


page_handle_dialog = as_cli()(wrap_core(_core_func, "handled"))

if __name__ == "__main__":
    page_handle_dialog.cli_main()
