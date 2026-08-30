"""Regression: _parse_docstring_args must survive real multi-line Args blocks.

The docstring is the SSOT for every CLI arg's --help text (cli-steering Rule 4).
The parser used to (a) treat any continuation line containing ': ' as a new arg
and (b) end the Args block on any line ending in ':' — so in a docstring like
browser_start's, every arg after the first wrapped one silently lost its help
and fell back to a bare "(type)" placeholder. These pin the fix.
"""

from __future__ import annotations

from ai_dev_browser._cli import _parse_docstring_args


def test_wrapped_arg_with_embedded_colon_does_not_swallow_later_args():
    doc = """Summary.

    Args:
        headless: Run in headless mode. Accepts `False` (default,
            windowed), `True` / `"new"` (new headless: full Chrome
            architecture), or `"old"` (legacy headless — falls back to
            the `AI_DEV_BROWSER_HEADLESS` env var:
            `1`/`true` -> True.
        url: Initial URL to open.
        profile: Named profile for persistence.

    Returns:
        dict.
    """
    got = _parse_docstring_args(doc)
    # Every declared arg is captured...
    assert set(got) == {"headless", "url", "profile"}, got
    # ...the wrapped headless description is joined whole (embedded ': ' kept)...
    assert "new headless: full Chrome" in got["headless"]
    assert got["headless"].endswith("-> True.")
    # ...and the args after the wrapped one are NOT lost.
    assert got["url"] == "Initial URL to open."
    assert got["profile"] == "Named profile for persistence."


def test_single_word_header_ends_block_but_wrapped_colon_line_does_not():
    doc = """S.

    Args:
        a: first, mentions env var: still same arg
            continues here.
        b: second.

    Raises:
        ValueError: nope, not an arg.
    """
    got = _parse_docstring_args(doc)
    assert set(got) == {"a", "b"}, got
    assert "still same arg continues here." in got["a"]
    # The Raises: entry must not leak in as an arg.
    assert "ValueError" not in got


def test_no_args_section():
    assert _parse_docstring_args("Just a summary, no Args.") == {}
    assert _parse_docstring_args("") == {}
