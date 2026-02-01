"""Focus an element on the page."""

from ai_dev_browser.core import focus_element

from .._cli import as_cli, wrap_core


element_focus = as_cli()(wrap_core(focus_element, "focused"))

if __name__ == "__main__":
    element_focus.cli_main()
