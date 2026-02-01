"""Execute JavaScript in the page."""

from ai_dev_browser.core import eval_js

from .._cli import as_cli, wrap_core


page_eval = as_cli()(wrap_core(eval_js, "result"))

if __name__ == "__main__":
    page_eval.cli_main()
