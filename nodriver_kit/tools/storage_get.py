"""Get localStorage value.

CLI:
    python -m nodriver_kit.tools.storage_get --key "token"

Python:
    from nodriver_kit.tools import storage_get
    result = await storage_get(tab, key="token")
"""

from nodriver_kit.core import get_local_storage
from ._cli import as_cli


@as_cli
async def storage_get(tab, key: str = None) -> dict:
    """Get localStorage value.

    Args:
        tab: Browser tab
        key: Key to get (if None, returns all)

    Returns:
        {"value": ...} or {"storage": {...}}
    """
    try:
        result = await get_local_storage(tab, key=key)
        if key:
            return {"key": key, "value": result}
        else:
            return {"storage": result}
    except Exception as e:
        return {"error": f"Get storage failed: {e}"}


if __name__ == "__main__":
    storage_get.cli_main()
