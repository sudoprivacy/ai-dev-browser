"""Execute JavaScript in the page context."""

from ai_dev_browser.core import js_exec as core_js_exec

from .._cli import as_cli, wrap_core


js_exec = as_cli()(wrap_core(core_js_exec, "result"))

if __name__ == "__main__":
    js_exec.cli_main()
