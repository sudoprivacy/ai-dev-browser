"""Set localStorage value."""

from ai_dev_browser.core import set_local_storage
from .._cli import as_cli


@as_cli()
async def storage_set(tab, key: str, value: str) -> dict:
    """Set localStorage value.

    Args:
        tab: Browser tab
        key: Key to set
        value: Value to set
    """
    try:
        await set_local_storage(tab, items={key: value})
        return {"set": True, "key": key, "value": value}
    except Exception as e:
        return {"error": f"Set storage failed: {e}"}


if __name__ == "__main__":
    storage_set.cli_main()
