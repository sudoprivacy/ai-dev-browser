"""Navigate to a URL."""

from ai_dev_browser.core import goto
from .._cli import as_cli, wrap_core

# True SSOT: parameters defined once in core.goto, CLI inherits automatically
page_goto = as_cli()(wrap_core(goto, "success"))

if __name__ == "__main__":
    page_goto.cli_main()
