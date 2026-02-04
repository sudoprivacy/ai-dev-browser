"""Type text into element located by its accessible name."""

from ai_dev_browser.core.elements import type_by_text as core_type_by_text

from .._cli import as_cli, wrap_core


type_by_text = as_cli()(wrap_core(core_type_by_text, "typed"))

if __name__ == "__main__":
    type_by_text.cli_main()
