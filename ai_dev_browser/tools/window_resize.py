"""Resize browser window."""

from ai_dev_browser.core import resize_window

from .._cli import as_cli, wrap_core


window_resize = as_cli()(wrap_core(resize_window, "resized"))

if __name__ == "__main__":
    window_resize.cli_main()
