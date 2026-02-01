"""Open a new tab."""

from ai_dev_browser.core import new_tab

from .._cli import as_cli, wrap_core


tab_new = as_cli()(wrap_core(new_tab, "opened"))

if __name__ == "__main__":
    tab_new.cli_main()
