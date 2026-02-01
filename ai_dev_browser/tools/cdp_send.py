"""Send CDP command."""

from ai_dev_browser.core import send_cdp_command

from .._cli import as_cli, wrap_core


cdp_send = as_cli()(wrap_core(send_cdp_command, "result"))

if __name__ == "__main__":
    cdp_send.cli_main()
