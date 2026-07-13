"""CDP Runtime result → Python value. The single unwrapping SSOT.

`Runtime.evaluate` (Tab.evaluate) and `Runtime.callFunctionOn`
(Element.apply) both answer with the same CDP pair:
`(RemoteObject, ExceptionDetails)`. Neither half of that pair is a Python
value — the exception is a protocol object, and a non-primitive result
arrives wrapped in CDP's deep-serialization envelope
(`[[key, {"type": ..., "value": ...}], ...]`).

Turning that pair into "a Python value, or an exception" is therefore one
concern, and it lives here once. Both call sites used to hand-roll it, and
both hand-rolled it wrong in the same way: they returned the protocol
object into the value channel, so a page-side throw reached the caller as
a *return value* that silently type-shifted.
"""

from __future__ import annotations

from typing import Any

from .errors import JsEvaluationError

# Deep-serialized types with no Python representation.
#
# These are NOT errors. The expression ran fine; it just produced something —
# a DOM node, a pending promise — that has no value on this side of the wire.
# Raising here would break every side-effect caller that ignores the result:
# `window.scrollBy(0, 100)` deep-serializes as a *promise* in current Chrome,
# and page_scroll doesn't care.
#
# Returning bare None would be worse than useless, though: an LLM reading
# `{"result": null}` from `document.querySelector('#x')` concludes the element
# is absent, which is the exact class of silent-wrong-answer this module
# exists to kill. So the value channel carries a flat, terminal, JSON-safe
# marker that says what came back and what to do about it.
_OPAQUE: dict[str, str] = {
    "function": (
        "a function object — it was never called. Wrap it in an IIFE: `(() => { ... })()`"
    ),
    "promise": (
        "a pending promise — pass await_promise=True to resolve it. "
        "(Harmless if you called this for its side effect.)"
    ),
    "node": (
        "a DOM node, which cannot cross the CDP boundary. Return a plain value "
        "instead (e.g. `el.textContent`, `el.value`), or locate the element with "
        "find_by_text / find_by_xpath / html_by_ref"
    ),
    "nodelist": (
        "a DOM NodeList, which cannot cross the CDP boundary. Map it to plain "
        "values first, e.g. `[...document.querySelectorAll('a')].map(a => a.href)`"
    ),
    "htmlcollection": (
        "an HTMLCollection, which cannot cross the CDP boundary. Map it to plain "
        "values first, e.g. `[...el.children].map(c => c.tagName)`"
    ),
    "window": "a Window object, which cannot cross the CDP boundary",
    "symbol": "a Symbol, which has no Python representation",
    "error": (
        "an Error object that was *returned* rather than thrown. Return "
        "`err.message` for the text, or `throw` it to fail the call"
    ),
}


def _opaque_marker(type_: str) -> dict[str, str]:
    hint = _OPAQUE.get(type_, "a value with no Python representation")
    return {"__js_type__": type_, "hint": f"expression returned {hint}"}


_NUMERIC_LITERALS: dict[str, float] = {
    "NaN": float("nan"),
    "Infinity": float("inf"),
    "-Infinity": float("-inf"),
    "-0": -0.0,
}


def _split(node: Any) -> tuple[str | None, Any]:
    """Read (type, value) off a deep-serialized node.

    The cdp module parses only the outermost `DeepSerializedValue` into a
    dataclass; everything nested inside stays a raw dict. Both shapes show
    up during one recursion, so accept both here rather than making callers
    care which level they're on.
    """
    if isinstance(node, dict):
        return node.get("type"), node.get("value")
    return getattr(node, "type_", None), getattr(node, "value", None)


def _number(value: Any) -> Any:
    # CDP sends the non-JSON-representable numbers as strings.
    if isinstance(value, str):
        return _NUMERIC_LITERALS.get(value, value)
    return value


def _from_deep(node: Any, expression: str | None) -> Any:
    type_, value = _split(node)

    if type_ in ("undefined", "null"):
        return None
    if type_ in ("string", "boolean"):
        return value
    if type_ == "number":
        return _number(value)
    if type_ == "bigint":
        return int(value)
    # Already plain: an ISO-8601 string, and {"pattern", "flags"}.
    if type_ in ("date", "regexp"):
        return value
    if type_ in ("array", "set"):
        return [_from_deep(item, expression) for item in (value or [])]
    if type_ in ("object", "map"):
        out: dict = {}
        for key, val in value or []:
            # Object keys are plain strings; Map keys can be any deep node.
            k = (
                key
                if isinstance(key, (str, int, float, bool))
                else _from_deep(key, expression)
            )
            if not isinstance(k, (str, int, float, bool, type(None))):
                k = str(k)  # unhashable Map key (object/array) — stringify
            out[k] = _from_deep(val, expression)
        return out

    return _opaque_marker(str(type_))


def _from_exception_details(
    exc_details: Any, expression: str | None
) -> JsEvaluationError:
    exception = getattr(exc_details, "exception", None)
    # `text` is CDP's generic wrapper — literally the string "Uncaught". The
    # exception's own `description` is what carries "Error: <msg>" plus the
    # JS stack, which is the only part a caller can act on.
    message = (
        getattr(exception, "description", None)
        or getattr(exc_details, "text", None)
        or "JavaScript error"
    )
    stack_trace = getattr(exc_details, "stack_trace", None)
    frames = [
        {
            "function": frame.function_name,
            "url": frame.url,
            "line": frame.line_number,
            "column": frame.column_number,
        }
        for frame in (stack_trace.call_frames if stack_trace else [])
    ]
    return JsEvaluationError(message, expression=expression, stack=frames)


def unwrap(
    remote_object: Any, exception_details: Any, *, expression: str | None = None
) -> Any:
    """Turn a CDP `(RemoteObject, ExceptionDetails)` pair into a Python value.

    Raises:
        JsEvaluationError: the expression threw, or produced a value that
            cannot cross the CDP boundary.
    """
    if exception_details is not None:
        raise _from_exception_details(exception_details, expression)

    if remote_object is None:
        return None

    deep = getattr(remote_object, "deep_serialized_value", None)
    if deep is not None:
        return _from_deep(deep, expression)

    # return_by_value / callFunctionOn path — CDP already sent a plain value.
    return getattr(remote_object, "value", None)
