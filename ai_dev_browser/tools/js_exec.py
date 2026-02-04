"""AUTO-GENERATED from ai_dev_browser.core.page.js_exec
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.page import js_exec as _core_func

from .._cli import as_cli, wrap_core


js_exec = as_cli()(wrap_core(_core_func, "result"))

if __name__ == "__main__":
    js_exec.cli_main()
