"""AUTO-GENERATED from ai_dev_browser.core.elements.wait_for_element_with_info
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.elements import wait_for_element_with_info as _core_func

from .._cli import as_cli, wrap_core


element_wait = as_cli()(wrap_core(_core_func, "found"))

if __name__ == "__main__":
    element_wait.cli_main()
