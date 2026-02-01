"""Bring browser window to front."""

from ai_dev_browser.core import focus_window

from .._cli import as_cli, wrap_core


window_focus = as_cli()(wrap_core(focus_window, "focused"))

if __name__ == "__main__":
    window_focus.cli_main()
