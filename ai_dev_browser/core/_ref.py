"""The `ref` grammar — one definition, one parser.

A `ref` is how this library names an element across a CDP round trip:

    "5#214"                 index 5 in the snapshot, backend node id 214
    "FRAME_ABC123:5#214"    the same, inside the frame whose id starts ABC123
    "5"                     legacy — index only, no node id

`snapshot.py` mints refs, `ax.py` resolves them. Neither is a natural owner of
the grammar, and when each kept its own copy the format was encoded in three
places (plus `_element.py`, which had no business knowing it at all) — one with
a regex, one with `ref.split("#")[-1]`. Changing the format meant finding all of
them; missing one meant a silent `int()` crash on a ref that used to parse.
"""

from __future__ import annotations

import re

_FRAME_PREFIX = re.compile(r"^(FRAME_[^:]+):(.+)$")
_INDEXED_NODE = re.compile(r"^(\d+)#(\d+)$")


def make_ref(index: int, backend_node_id: int | None = None) -> str:
    """Mint a ref. The inverse of `parse_ref`."""
    if backend_node_id is None:
        return str(index)
    return f"{index}#{backend_node_id}"


def parse_ref(ref: str) -> tuple[str | None, str, int | None]:
    """Split a ref into (frame_prefix, local_ref, backend_node_id).

    Examples:
        "9#214"                 -> (None, "9", 214)
        "FRAME_ABC123:9#214"    -> ("FRAME_ABC123", "9", 214)
        "9"                     -> (None, "9", None)   # legacy, no node id
    """
    frame_prefix = None
    local_ref = ref
    backend_node_id = None

    frame_match = _FRAME_PREFIX.match(ref)
    if frame_match:
        frame_prefix = frame_match.group(1)
        local_ref = frame_match.group(2)

    node_match = _INDEXED_NODE.match(local_ref)
    if node_match:
        local_ref = node_match.group(1)
        backend_node_id = int(node_match.group(2))

    return frame_prefix, local_ref, backend_node_id


def node_id_of(ref: str) -> int | None:
    """The backend node id a ref points at, or None for a legacy index-only ref."""
    return parse_ref(ref)[2]
