"""The structured-but-backward-compatible failure signal (cli-steering 5b + 7).

Guards that every failure return keeps the verbatim `error` string and top-level
`hint` (a live integrator reads both) AND gains a stable `error_code` + a
conservative `retryable` flag, and that the CLI exits with a semantic code on a
hard failure only.
"""

from __future__ import annotations

import asyncio

from ai_dev_browser._cli import (
    _augment_failure,
    _classify_error,
    _exit_code_for_result,
    wrap_core,
    wrap_core_sync,
)


def test_classify_error_is_conservative():
    assert _classify_error("Failed to connect to Chrome on 127.0.0.1:9350") == (
        "transient",
        True,
    )
    assert _classify_error("WebSocket send failed") == ("transient", True)
    # a timeout is NOT retryable — the caller should follow the hint, not loop
    assert _classify_error("CDP command timed out after 5.0s") == ("timeout", False)
    assert _classify_error("Element not found for ref 5#9") == ("not_found", False)
    assert _classify_error("Port 9350 is already in use") == ("conflict", False)
    assert _classify_error("Must specify ref or node_id") == ("validation", False)
    # page_pdf size-parse errors are validation (fix the value, don't retry)
    assert _classify_error("paper_width: unknown unit 'furlong'") == (
        "validation",
        False,
    )
    assert _classify_error("paper: unknown preset 'foo'") == ("validation", False)
    # unrecognized -> generic, never retryable
    assert _classify_error("something odd") == ("error", False)
    assert _classify_error("") == ("error", False)
    assert _classify_error(None) == ("error", False)


def test_augment_failure_is_additive_and_respects_tool_values():
    out = _augment_failure({"error": "timed out", "hint": "x"}, "timed out")
    assert out["error"] == "timed out" and out["hint"] == "x"  # preserved verbatim
    assert out["error_code"] == "timeout" and out["retryable"] is False
    # a core function that already knows better wins (setdefault, not overwrite)
    keep = _augment_failure(
        {"error": "timed out", "retryable": True, "error_code": "custom"}, "timed out"
    )
    assert keep["retryable"] is True and keep["error_code"] == "custom"


def test_exit_code_only_nonzero_for_hard_failure():
    assert _exit_code_for_result({"clicked": True}) == 0  # success
    assert _exit_code_for_result({"clicked": False, "hint": "x"}) == 0  # soft dict fail
    assert _exit_code_for_result({"error": "boom"}) == 1  # error, no code
    assert (
        _exit_code_for_result(
            _augment_failure({"error": "failed to connect"}, "failed to connect")
        )
        == 9
    )
    assert (
        _exit_code_for_result(_augment_failure({"error": "not found"}, "not found"))
        == 4
    )
    assert _exit_code_for_result(["a", "b"]) == 0  # a catalog list is not a failure


def test_wrap_core_sync_envelope_end_to_end():
    def raises(x):
        raise RuntimeError("Element not found for ref 5#9")

    def soft_fail(x):
        return {"clicked": False, "error": "CDP command timed out after 5.0s"}

    def catalog(x):
        return [{"a": 1}, {"a": 2}]

    def ok(x):
        return {"clicked": True, "method": "synthetic"}

    r = wrap_core_sync(raises, "clicked")(1)
    assert r["error"] == "Element not found for ref 5#9"  # verbatim, backward-compat
    assert r["error_code"] == "not_found" and r["retryable"] is False

    r = wrap_core_sync(soft_fail, "clicked")(1)
    assert r["clicked"] is False and r["error"].startswith("CDP command timed out")
    assert r["error_code"] == "timeout" and r["retryable"] is False

    # catalog lists pass through untouched (Rule 5) — no envelope keys injected
    assert wrap_core_sync(catalog, "elements")(1) == [{"a": 1}, {"a": 2}]

    # a success carries no failure fields
    r = wrap_core_sync(ok, "clicked")(1)
    assert "error_code" not in r and "retryable" not in r


def test_wrap_core_async_exception_envelope():
    async def raises(tab):
        raise ConnectionError("Failed to connect to Chrome on 127.0.0.1:9350")

    r = asyncio.run(wrap_core(raises, "clicked")(None))
    assert r["error_code"] == "transient" and r["retryable"] is True
