"""Close a tab."""

from ai_dev_browser.core import close_tab

from .._cli import as_cli, wrap_core


tab_close = as_cli()(wrap_core(close_tab, "closed"))

if __name__ == "__main__":
    tab_close.cli_main()
