"""Focus element by ref from find()."""

from ai_dev_browser.core.ax import focus_by_ref as core_focus_by_ref

from .._cli import as_cli, wrap_core


focus_by_ref = as_cli()(wrap_core(core_focus_by_ref, "focused"))

if __name__ == "__main__":
    focus_by_ref.cli_main()
