"""List open tabs."""

from ai_dev_browser.core import list_tabs

from .._cli import as_cli, wrap_core


tab_list = as_cli()(wrap_core(list_tabs, "tabs"))

if __name__ == "__main__":
    tab_list.cli_main()
