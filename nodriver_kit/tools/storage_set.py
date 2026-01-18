"""Set localStorage value.

CLI:
    python -m nodriver_kit.tools.storage_set --key "token" --value "abc123"

Python:
    from nodriver_kit.tools import storage_set
    result = await storage_set(tab, key="token", value="abc123")
"""

from nodriver_kit.core import set_local_storage
from ._cli import as_cli


@as_cli
async def storage_set(tab, key: str, value: str) -> dict:
    """Set localStorage value.

    Args:
        tab: Browser tab
        key: Key to set
        value: Value to set

    Returns:
        {"set": True, "key": ..., "value": ...}
    """
    try:
        await set_local_storage(tab, items={key: value})
        return {"set": True, "key": key, "value": value}
    except Exception as e:
        return {"error": f"Set storage failed: {e}"}


if __name__ == "__main__":
    storage_set.cli_main()
