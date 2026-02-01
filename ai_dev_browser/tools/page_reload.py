"""Reload the page."""

from ai_dev_browser.core import reload
from .._cli import as_cli, wrap_core

# True SSOT: parameters defined once in core.reload, CLI inherits automatically
page_reload = as_cli()(wrap_core(reload, "reloaded"))

if __name__ == "__main__":
    page_reload.cli_main()
