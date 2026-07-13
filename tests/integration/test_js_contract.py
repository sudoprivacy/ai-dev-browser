"""`Tab.evaluate` returns a Python value, or raises. It never returns a
protocol object.

CDP answers `Runtime.evaluate` with a `(RemoteObject, ExceptionDetails)` pair.
`Tab.evaluate` used to hand both halves back through the *value* channel:

  - a page-side `throw` came back as an `ExceptionDetails` **return value**, so
    `js_evaluate(tab, "if (bad) throw new Error('x')")` — the obvious way to
    write an assertion — passed silently for every caller that read `.result`;
  - any non-primitive came back wrapped in CDP's deep-serialization envelope
    (`[[key, {"type": ..., "value": ...}], ...]`), which is why callers had to
    round-trip through `JSON.stringify` to get a dict.

Both are closed in `_js.unwrap`, the one place that turns that CDP pair into a
Python value. These tests pin the contract from the outside so it cannot rot
back: a throw must raise, values must arrive as plain Python, and — the part
that is easy to get wrong in the other direction — a value CDP cannot serialise
must NOT raise, because side-effect callers ignore the return. `window.scrollBy`
deep-serialises as a *promise* in current Chrome, and `page_scroll` does not
care.
"""

from __future__ import annotations

import os

import pytest

from ai_dev_browser.core import JsEvaluationError, js_evaluate, page_goto
from ai_dev_browser.core._transport import CommandTimeout
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, get_active_tab

SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


@pytest.fixture
async def tab():
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    try:
        browser = await connect_browser(port=port)
        the_tab = await get_active_tab(browser)
        await page_goto(the_tab, "data:text/html,<title>t</title><body>hi")
        yield the_tab
    finally:
        browser_stop(port=port)


# ---------------------------------------------------------------------------
# Error channel — a throw is a failure, not a result
# ---------------------------------------------------------------------------


async def test_js_throw_raises_instead_of_returning(tab):
    with pytest.raises(JsEvaluationError) as exc:
        await tab.evaluate("throw new Error('BOOM')")

    message = str(exc.value)
    assert "BOOM" in message
    # The JS message *and* its source location, not CDP's generic wrapper — the
    # ExceptionDetails `text` field is the literal string "Uncaught", which is
    # what the old error path surfaced and which tells a caller nothing.
    assert "Uncaught" != exc.value.message
    assert "at <anonymous>" in message, "JS source location must reach the caller"


async def test_js_evaluate_assertion_fails_loudly(tab):
    """The pattern an e2e suite reaches for. It used to pass silently: the
    error was tucked into `result["error"]` beside `result["result"]`, and
    callers read `.result`."""
    with pytest.raises(JsEvaluationError) as exc:
        await js_evaluate(
            tab, "if (1 !== 2) { throw new Error('want 2, got 1'); } true"
        )

    assert "want 2, got 1" in str(exc.value)


async def test_js_evaluate_failure_carries_console_trail(tab):
    """Console output emitted before the throw is how you find out *why* the
    page was in the failing state. It belongs on the failure, not in a success
    dict nobody reads."""
    with pytest.raises(JsEvaluationError) as exc:
        await js_evaluate(tab, "console.log('count was', 7); throw new Error('nope')")

    assert any("7" in entry["text"] for entry in exc.value.console)
    assert "console.log" in str(exc.value)


async def test_top_level_return_is_a_syntax_error(tab):
    """`return true` at top level is illegal JS. It used to be swallowed, so an
    assertion written that way reported success while never running."""
    with pytest.raises(JsEvaluationError) as exc:
        await js_evaluate(tab, "if (0) throw new Error('x'); return true")

    assert "SyntaxError" in str(exc.value)


async def test_error_names_the_expression(tab):
    """Long suites run hundreds of evals; "which one hung/threw" is the whole
    question."""
    with pytest.raises(JsEvaluationError) as exc:
        await tab.evaluate("nope.nothing.here")
    assert "nope.nothing.here" in str(exc.value)


async def test_timeout_names_the_expression(tab):
    with pytest.raises(CommandTimeout) as exc:
        await tab.evaluate(
            "new Promise(r => setTimeout(r, 5000))", await_promise=True, timeout=1
        )
    assert "setTimeout" in str(exc.value)


# ---------------------------------------------------------------------------
# Value channel — plain Python, no CDP envelopes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("1 + 1", 2),
        ("'hi'", "hi"),
        ("true", True),
        ("null", None),
        ("undefined", None),
        ("[1, 2, 3]", [1, 2, 3]),
        ("({a: 1, b: [1, {c: 'x'}]})", {"a": 1, "b": [1, {"c": "x"}]}),
        ("new Map([['k', 1]])", {"k": 1}),
        ("new Set([1, 2])", [1, 2]),
        ("10n", 10),
    ],
)
async def test_values_arrive_as_plain_python(tab, expression, expected):
    assert await tab.evaluate(expression) == expected


async def test_object_needs_no_json_round_trip(tab):
    """The `JSON.stringify(...)` + `json.loads(...)` ceremony every call site
    used to perform is gone, because the envelope never reaches them."""
    result = await js_evaluate(tab, "({url: location.href, n: 42})")
    assert result["result"]["n"] == 42


# ---------------------------------------------------------------------------
# Unserialisable values are NOT errors
# ---------------------------------------------------------------------------


async def test_side_effect_returning_a_promise_does_not_raise(tab):
    """`window.scrollBy` deep-serialises as a promise in current Chrome. Raising
    on unserialisable values would break every caller that runs JS purely for
    its side effect — which is most of them."""
    await tab.evaluate("window.scrollBy(0, 10)")  # must not raise


@pytest.mark.parametrize(
    "expression,js_type",
    [
        ("document.body", "node"),
        ("() => 1", "function"),
        ("Promise.resolve(1)", "promise"),
    ],
)
async def test_unserialisable_value_is_reported_not_swallowed(tab, expression, js_type):
    """Returning bare None here would be the same disease under a new name: an
    LLM reading `{"result": null}` from a `querySelector` concludes the element
    is absent. Say what came back and how to ask for it properly."""
    marker = await tab.evaluate(expression)
    assert marker["__js_type__"] == js_type
    assert marker["hint"]
