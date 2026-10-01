"""Regression: _parse_docstring_args must survive real multi-line Args blocks.

The docstring is the SSOT for every CLI arg's --help text (cli-steering Rule 4).
The parser used to (a) treat any continuation line containing ': ' as a new arg
and (b) end the Args block on any line ending in ':' — so in a docstring like
browser_start's, every arg after the first wrapped one silently lost its help
and fell back to a bare "(type)" placeholder. These pin the fix.
"""

from __future__ import annotations

from ai_dev_browser._cli import (
    _generate_parser,
    _parse_docstring_args,
    _parse_docstring_summary,
    wrap_core,
)


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


async def test_help_routes_args_once_and_recovery_to_runtime():
    async def save(out: str):
        """Use when: saving a result. Returns its path.

        Continue with the returned path.

        Args:
            out: Destination that must be writable.

        Failure:
            Choose a writable destination and try again.
        """
        raise PermissionError(out)

    wrapped = wrap_core(save)
    help_text = _generate_parser(wrapped, requires_tab=False).format_help()
    assert "Continue with the returned path." in help_text
    assert help_text.count("Destination that must be writable.") == 1
    assert "Args:" not in help_text and "Failure:" not in help_text
    assert "Choose a writable destination" not in help_text
    failure = await wrapped("/read-only/output.gif")
    assert failure["hint"] == "Choose a writable destination and try again."
    assert failure["retryable"] is False


def test_summary_without_args_preserves_prose_and_stops_at_failure():
    doc = """Use when: you need a result.

    Next step:
        Read it.

    Failure:
        Start again.
    """
    assert _parse_docstring_summary(doc) == (
        "Use when: you need a result.\n\nNext step:\n    Read it."
    )
    assert _parse_docstring_summary("") == ""
