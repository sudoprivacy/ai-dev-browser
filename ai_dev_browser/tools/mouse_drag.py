"""Drag mouse from one point to another."""

from ai_dev_browser.core import mouse_drag as core_mouse_drag
from .._cli import as_cli, wrap_core

# True SSOT: parameters defined once in core.mouse_drag, CLI inherits automatically
# Note: CLI params are from_x/from_y/to_x/to_y (matching core)
mouse_drag = as_cli()(wrap_core(core_mouse_drag, "dragged"))

if __name__ == "__main__":
    mouse_drag.cli_main()
