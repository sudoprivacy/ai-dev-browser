"""AUTO-GENERATED from ai_dev_browser.core.elements.type_by_text
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.elements import type_by_text as _core_func

from .._cli import as_cli, wrap_core


type_by_text = as_cli()(wrap_core(_core_func, "typed"))

if __name__ == "__main__":
    type_by_text.cli_main()
