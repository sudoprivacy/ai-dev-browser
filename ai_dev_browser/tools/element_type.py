"""Type text into an element."""

from ai_dev_browser.core import type_text
from .._cli import as_cli, wrap_core

# True SSOT: parameters defined once in core.type_text, CLI inherits automatically
element_type = as_cli()(wrap_core(type_text, "typed"))

if __name__ == "__main__":
    element_type.cli_main()
