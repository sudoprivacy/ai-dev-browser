"""Smell test: scan codebase for telltale broken-acronym snake_case.

If something in the code emits names like `_c_s_p`, `_u_r_l`, `_h_t_m_l`
or other obvious acronym splits, it's almost certainly the naive
`re.sub(r"(?<!^)(?=[A-Z])", "_", name)` regex creeping back. This test
catches it before someone tries to call cdp-python with such a kwarg.

Cheap to run, hard to false-positive. Allowed by exclusion only when a
pattern legitimately appears in code (e.g. inside a comment quoting the
old wrong output).
"""

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = [REPO_ROOT / "ai_dev_browser"]
EXCLUDE_DIRS = {"cdp", "__pycache__"}  # vendored auto-generated CDP module
EXCLUDE_FILES = {
    # This very test file mentions the patterns by definition.
    Path(__file__).resolve(),
    # _case.py docstring quotes them as the wrong-output examples.
    REPO_ROOT / "ai_dev_browser" / "core" / "_case.py",
}

# Patterns that strongly indicate a botched camel→snake conversion.
# Real snake_case variables of the form `_c_s_p` essentially never occur
# in human-written code, so any match is suspicious.
SUSPICIOUS_PATTERNS = [
    "_c_s_p",
    "_u_r_l",
    "_h_t_m_l",
    "_h_t_t_p",
    "_x_m_l",
    "_a_p_i",
    "_j_s_o_n",
]


def _iter_python_files():
    for root in SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if any(part in EXCLUDE_DIRS for part in path.relative_to(root).parts):
                continue
            if path.resolve() in EXCLUDE_FILES:
                continue
            yield path


@pytest.mark.parametrize("pattern", SUSPICIOUS_PATTERNS)
def test_no_broken_acronym_snake_case(pattern):
    """No source file should contain {pattern} — that's the fingerprint
    of the naive regex camel-to-snake bug shipped pre-v0.4.5."""
    offenders = []
    for path in _iter_python_files():
        text = path.read_text(encoding="utf-8")
        if pattern in text:
            offenders.append(path)
    assert not offenders, (
        f"Found suspicious acronym-split substring {pattern!r} in:\n  "
        + "\n  ".join(str(p) for p in offenders)
        + "\n\nThis usually means the broken naive regex "
        + "re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower() crept back. "
        + "Use ai_dev_browser.core._case.camel_to_snake instead."
    )
