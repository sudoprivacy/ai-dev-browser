"""Local storage operations."""

from ._tab import Tab


async def get_local_storage(
    tab: Tab,
    key: str | None = None,
) -> dict:
    """Get localStorage data.

    Args:
        tab: Tab instance
        key: Specific key to get (default: all)

    Returns:
        dict with value (single key) or items (all keys)
    """
    storage = await tab.get_local_storage()

    if key is not None:
        return {"key": key, "value": storage.get(key)}
    return {"items": storage, "count": len(storage)}


async def set_local_storage(
    tab: Tab,
    items: dict | None = None,
    key: str | None = None,
    value: str | None = None,
) -> dict:
    """Set localStorage data.

    Args:
        tab: Tab instance
        items: dict of key-value pairs to set (batch mode)
        key: Single key to set (simple mode)
        value: Value for single key (simple mode)

    Returns:
        dict with set count or key/value
    """
    if key is not None and value is not None:
        await tab.set_local_storage({key: value})
        return {"key": key, "value": value}
    elif items:
        await tab.set_local_storage(items)
        return {"set": len(items)}
    else:
        return {"error": "Must specify items dict or key/value pair"}
