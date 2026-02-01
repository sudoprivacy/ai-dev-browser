"""Set window state (maximize, minimize, fullscreen)."""

from ai_dev_browser.core import set_window_state

from .._cli import as_cli, wrap_core


window_state = as_cli()(wrap_core(set_window_state, "state"))

if __name__ == "__main__":
    window_state.cli_main()
