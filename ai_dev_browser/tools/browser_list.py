"""List running browser instances."""

from ai_dev_browser.core import list_browsers

from .._cli import as_cli, wrap_core_sync


browser_list = as_cli(requires_tab=False)(wrap_core_sync(list_browsers, "browsers"))

if __name__ == "__main__":
    browser_list.cli_main()
