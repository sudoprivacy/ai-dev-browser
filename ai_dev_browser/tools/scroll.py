"""Scroll the page."""

from ai_dev_browser.core import scroll as core_scroll

from .._cli import as_cli, wrap_core


# True SSOT: parameters defined once in core.scroll, CLI inherits automatically
scroll = as_cli()(wrap_core(core_scroll, "scrolled"))

if __name__ == "__main__":
    scroll.cli_main()
