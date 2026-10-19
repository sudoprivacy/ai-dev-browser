"""Local storage operations."""

from ._tab import Tab


async def storage_get(
    tab: Tab,
    key: str | None = None,
) -> dict:
    """Use when: reading localStorage on the selected page's origin; returns value for a key or items and count.

    Args:
        tab: Tab instance
        key: Specific key to get (default: all)

    Returns:
        dict with value (single key) or items (all keys)

    Failure:
        Navigate to the intended HTTP(S) origin first; localStorage may be
        unavailable on blank or restricted pages. A null value means the key is
        absent on this origin.
    """
    storage = await tab.storage_get()

    if key is not None:
        return {"key": key, "value": storage.get(key)}
    return {"items": storage, "count": len(storage)}


async def storage_set(
    tab: Tab,
    items: dict | None = None,
    key: str | None = None,
    value: str | None = None,
) -> dict:
    """Use when: writing localStorage on the selected page's origin; returns verified with the observed value or written count.

    Supply a key/value pair or a JSON items object. The write is read back on
    the same origin; verified confirms the values without another tool call.

    Args:
        tab: Tab instance
        items: dict of key-value pairs to set (batch mode)
        key: Single key to set (simple mode)
        value: Value for single key (simple mode)

    Returns:
        dict with verified and set count or observed key/value

    Failure:
        Supply either items as a JSON object or both key and value. Select the
        intended origin first; inspect storage_get after an uncertain write
        before deciding whether to change it again.
    """
    if key is not None and value is not None:
        await tab.storage_set({key: value})
        observed = await tab.storage_get()
        result = {"key": key, "value": observed.get(key)}
        verified = observed.get(key) == value
    elif items:
        await tab.storage_set(items)
        observed = await tab.storage_get()
        result = {"set": len(items)}
        verified = all(observed.get(str(k)) == str(v) for k, v in items.items())
    else:
        return {"error": "Must specify items dict or key/value pair"}
    result["verified"] = verified
    if not verified:
        result.update(
            error="Storage write could not be verified; inspect current origin state",
            error_code="conflict",
            retryable=False,
        )
    return result
