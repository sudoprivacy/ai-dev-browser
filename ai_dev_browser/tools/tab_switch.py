"""Switch to a tab."""

from ai_dev_browser.core import switch_tab

from .._cli import as_cli, wrap_core


tab_switch = as_cli()(wrap_core(switch_tab, "switched"))

if __name__ == "__main__":
    tab_switch.cli_main()
