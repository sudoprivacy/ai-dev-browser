"""AUTO-GENERATED from ai_dev_browser.core.session.get_session_id
DO NOT EDIT - modify the core function instead, then run:
    python -m ai_dev_browser.tools._generate
"""

from ai_dev_browser.core.session import get_session_id as _core_func

from .._cli import as_cli, wrap_core


login_interactive = as_cli()(wrap_core(_core_func, "session_id"))

if __name__ == "__main__":
    login_interactive.cli_main()
