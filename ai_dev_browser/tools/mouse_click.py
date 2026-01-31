"""Click at coordinates."""

from ai_dev_browser.core import mouse_click as core_mouse_click
from .._cli import as_cli, wrap_core

# True SSOT: parameters defined once in core.mouse_click, CLI inherits automatically
mouse_click = as_cli()(wrap_core(core_mouse_click, "clicked"))

if __name__ == "__main__":
    mouse_click.cli_main()
