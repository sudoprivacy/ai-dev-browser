"""Handle JavaScript dialogs (alert, confirm, prompt, beforeunload).

Provides functionality to accept or dismiss browser dialogs that would
otherwise block automation scripts.
"""

from ai_dev_browser.core import handle_dialog_action

from .._cli import as_cli, wrap_core


page_handle_dialog = as_cli()(wrap_core(handle_dialog_action, "success"))

if __name__ == "__main__":
    page_handle_dialog.cli_main()
