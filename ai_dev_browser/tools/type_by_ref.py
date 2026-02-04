"""Type text into element by ref from find()."""

from ai_dev_browser.core.ax import type_by_ref as core_type_by_ref

from .._cli import as_cli, wrap_core


type_by_ref = as_cli()(wrap_core(core_type_by_ref, "typed"))

if __name__ == "__main__":
    type_by_ref.cli_main()
