"""Local storage operations."""

from typing import Any, Optional

import nodriver


async def get_local_storage(
    tab: nodriver.Tab,
    key: Optional[str] = None,
) -> Any:
    """Get localStorage data.

    Args:
        tab: Tab instance
        key: Specific key to get (default: all)

    Returns:
        Value for key, or dict of all items
    """
    storage = await tab.get_local_storage()

    if key is not None:
        return storage.get(key)
    return storage


async def set_local_storage(
    tab: nodriver.Tab,
    items: dict,
) -> None:
    """Set localStorage data.

    Args:
        tab: Tab instance
        items: dict of key-value pairs to set
    """
    await tab.set_local_storage(items)
