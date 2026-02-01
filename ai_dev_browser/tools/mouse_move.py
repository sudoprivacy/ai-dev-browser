"""Move mouse to coordinates."""

from ai_dev_browser.core import mouse_move as core_mouse_move
from .._cli import as_cli, wrap_core

# True SSOT: parameters defined once in core.mouse_move, CLI inherits automatically
mouse_move = as_cli()(wrap_core(core_mouse_move, "moved"))

if __name__ == "__main__":
    mouse_move.cli_main()
