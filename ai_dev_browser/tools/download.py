"""AUTO-GENERATED from ai_dev_browser.core — download
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core import download as _core_func

from .._cli import as_cli, wrap_core


download = as_cli()(wrap_core(_core_func, "success"))

if __name__ == "__main__":
    download.cli_main()
