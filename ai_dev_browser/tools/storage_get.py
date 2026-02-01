"""Get localStorage value."""

from ai_dev_browser.core import get_local_storage

from .._cli import as_cli, wrap_core


storage_get = as_cli()(wrap_core(get_local_storage, "value"))

if __name__ == "__main__":
    storage_get.cli_main()
