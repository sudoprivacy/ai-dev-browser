"""Guardrails for the tool-generation registry (`tools/_generate.py`).

`TOOL_META` is the SSOT for per-tool overrides (result_key, ...). It is keyed by
core function name, and `_discover_tools` only ever looks up keys for functions
it actually finds in `core.__all__`. So a key for a function that no longer
exists is silently dead config — it misleads a reader and rots as tools get
renamed. These tests keep the registry honest: every override must point at a
real tool, and every real tool that a wrapper is generated for must resolve.
"""

from __future__ import annotations

from ai_dev_browser.core import __all__ as core_all
from ai_dev_browser.tools._generate import INTERNAL, TOOL_META, _discover_tools


def test_tool_meta_has_no_stale_keys():
    """Every TOOL_META key must name a function exported from core.__all__ —
    otherwise it's dead config left behind by a rename (the class of debt this
    guard was added for: window_resize/window_state → window_set, etc.)."""
    stale = sorted(k for k in TOOL_META if k not in core_all)
    assert not stale, (
        f"TOOL_META references core functions that don't exist: {stale}. "
        "Delete the dead keys or restore the functions."
    )


def test_tool_meta_keys_are_not_marked_internal():
    """A tool can't be both configured for generation and excluded from it."""
    overlap = sorted(set(TOOL_META) & INTERNAL)
    assert not overlap, f"these are in both TOOL_META and INTERNAL: {overlap}"


def test_every_discovered_tool_is_generatable():
    """Discovery must yield a name + result_key for every tool, with no dupes —
    the invariant `_generate.main()` relies on to emit one file per tool."""
    tools = _discover_tools()
    names = [t["name"] for t in tools]
    assert names, "no tools discovered"
    assert len(names) == len(set(names)), "duplicate tool names discovered"
    for t in tools:
        assert t["result_key"], f"{t['name']} has an empty result_key"
