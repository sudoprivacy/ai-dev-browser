"""Set localStorage value."""

from ai_dev_browser.core import set_local_storage

from .._cli import as_cli, wrap_core


storage_set = as_cli()(wrap_core(set_local_storage, "set"))

if __name__ == "__main__":
    storage_set.cli_main()
