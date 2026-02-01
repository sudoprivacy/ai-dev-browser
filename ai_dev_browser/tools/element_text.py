"""Get text content of an element."""

from ai_dev_browser.core import get_element_text

from .._cli import as_cli, wrap_core


element_text = as_cli()(wrap_core(get_element_text, "text"))

if __name__ == "__main__":
    element_text.cli_main()
