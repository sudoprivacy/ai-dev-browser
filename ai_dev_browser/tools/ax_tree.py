"""Get accessibility tree of the page."""

from ai_dev_browser.core import get_accessibility_tree

from .._cli import as_cli, wrap_core


ax_tree = as_cli()(wrap_core(get_accessibility_tree, "elements"))

if __name__ == "__main__":
    ax_tree.cli_main()
