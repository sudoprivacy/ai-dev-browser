"""Exception types shared across core layers.

Lives in its own module because both `_tab.py` (Runtime.evaluate) and
`_element.py` (Runtime.callFunctionOn) raise `JsEvaluationError`, and
`_tab` already imports `_element` — a shared parent is the only import
order that avoids a cycle.
"""

from __future__ import annotations

# Expressions are frequently whole multi-line scripts. Error messages get
# read by an LLM in a terminal, so the snippet has to identify *which* eval
# failed without burying the actual error text under a wall of JS.
_SNIPPET_MAX = 120


def js_snippet(expression: str | None) -> str | None:
    """Collapse an expression to a single-line, length-capped identifier."""
    if not expression:
        return None
    flat = " ".join(expression.split())
    if len(flat) > _SNIPPET_MAX:
        flat = flat[: _SNIPPET_MAX - 1] + "…"
    return flat


class JsEvaluationError(Exception):
    """JavaScript run in the page did not produce a Python value.

    Two causes, both of which mean the caller's expression did not do what
    it intended, and both of which used to be reported by *returning* a
    protocol object into the value channel instead of raising:

    - The expression threw (`throw new Error(...)`, TypeError, SyntaxError).
    - The expression produced a value that cannot cross the CDP boundary
      (DOM node, function, pending promise, ...).

    Attributes carry the full fidelity for Python callers; `str(exc)` is
    the flattened text the CLI failure envelope and LLM callers read.
    """

    def __init__(
        self,
        message: str,
        *,
        expression: str | None = None,
        stack: list[dict] | None = None,
        console: list[dict] | None = None,
    ):
        self.message = message
        self.expression = expression
        self.stack = stack or []
        self.console = console or []
        super().__init__(message)

    def __str__(self) -> str:
        parts = [self.message]
        snippet = js_snippet(self.expression)
        if snippet:
            parts.append(f"  expression: {snippet}")
        # Console output emitted before the throw is often the only record of
        # how the page got into the failing state — dropping it on the floor
        # is what makes a failed assertion take a dozen rounds to diagnose.
        for entry in self.console:
            parts.append(
                f"  console.{entry.get('level', 'log')}: {entry.get('text', '')}"
            )
        return "\n".join(parts)
