"""CDP (Chrome DevTools Protocol) command operations."""

import inspect
import json
import typing

from ai_dev_browser import cdp as cdp_module

from ._case import camel_to_snake
from ._tab import Tab


def _coerce_value(value, annotation):
    """Turn a plain JSON value into the typed CDP object a binding param expects.

    The vendored bindings type object params as generated classes (e.g.
    `features: Optional[List[MediaFeature]]`) and serialize each with `.to_json()`
    — so a raw dict/list-of-dicts from `cdp_send` blows up with
    "'dict' object has no attribute 'to_json'". Each such class has a `from_json`;
    this rebuilds the object (recursing Optional/Union and List[...]) using the
    param's annotation. Anything without a `from_json` annotation passes through
    unchanged, so primitives and enums are untouched."""
    if annotation is None or value is None:
        return value
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Union:  # Optional[X] / Union[...]
        for arg in (a for a in args if a is not type(None)):
            coerced = _coerce_value(value, arg)
            if coerced is not value:
                return coerced
        return value
    if origin in (list, typing.List) and isinstance(value, list):
        elem = args[0] if args else None
        if elem is not None and hasattr(elem, "from_json"):
            return [
                elem.from_json(item) if isinstance(item, dict) else item
                for item in value
            ]
        return value
    if (
        isinstance(value, dict)
        and inspect.isclass(annotation)
        and hasattr(annotation, "from_json")
    ):
        return annotation.from_json(value)
    return value


def _coerce_params(cmd_func, params: dict) -> dict:
    """Coerce each param to the binding's annotated type (see _coerce_value).
    Best-effort — if the hints can't be resolved, params pass through as-is."""
    try:
        hints = typing.get_type_hints(cmd_func)
    except Exception:
        return params
    return {k: _coerce_value(v, hints.get(k)) for k, v in params.items()}


def _get_cdp_command(method: str, params: dict):
    """Dynamically create a CDP command generator.

    Args:
        method: CDP method like "Browser.getVersion" or "DOM.getDocument"
        params: Parameters dict

    Returns:
        CDP command generator
    """
    domain, cmd = method.split(".")
    domain_snake = camel_to_snake(domain)
    cmd_snake = camel_to_snake(cmd)

    # Get the domain module (e.g., cdp.browser)
    domain_mod = getattr(cdp_module, domain_snake)

    # Get the command function (e.g., cdp.browser.get_version)
    cmd_func = getattr(domain_mod, cmd_snake)

    # Rebuild object params (dict / list-of-dict) into the typed classes the
    # binding serializes with .to_json() — so an array-of-objects param like
    # setEmulatedMedia's `features` is reachable through cdp_send.
    params = _coerce_params(cmd_func, params)

    # Call with params
    return cmd_func(**params) if params else cmd_func()


# CDP methods whose effect is bound to the CDP session that issued them. adb's
# per-call model opens a FRESH session per tool call and closes it when the
# process exits, so the effect is gone before the next call — often before a
# follow-up click — while CDP still returns a bare success. That silence is the
# trap: a caller reads `{"result": null}` as "it worked" and only later finds
# the override never applied (a download in the default folder, the viewport
# unchanged). cdp_send attaches a `warning` for these, naming the tool that
# persists the effect (adb re-applies it every call) or owns the whole sequence
# in one attach. Keys are lowercased "domain.command".
_SESSION_SCOPED_METHODS = {
    "browser.setdownloadbehavior": (
        "the download still happens but lands in Chrome's DEFAULT folder, not "
        "your downloadPath. Use `download_link` (it owns click -> wait -> settle "
        "in one attach and honors download_dir), or `download` for a known URL."
    ),
    "page.setdownloadbehavior": (
        "the download still happens but lands in Chrome's DEFAULT folder, not "
        "your downloadPath. Use `download_link`, or `download` for a known URL."
    ),
    "emulation.setdevicemetricsoverride": (
        "the viewport reverts on the next tool call. Use `window_set` or the "
        "AI_DEV_BROWSER_VIEWPORT env, which adb re-applies every call."
    ),
    "emulation.cleardevicemetricsoverride": (
        "adb re-applies its default viewport on the next tool call. Set "
        "AI_DEV_BROWSER_VIEWPORT=native to disable the default, or `window_set`."
    ),
    "emulation.settimezoneoverride": (
        "reverts on the next tool call. Use `browser_start --timezone`, which "
        "adb re-applies every call."
    ),
    "emulation.setgeolocationoverride": (
        "reverts on the next tool call. Use `browser_start --geo`."
    ),
    "emulation.setlocaleoverride": (
        "reverts on the next tool call, and it only moves Intl, not "
        "navigator.language. Use `browser_start --locale` (which also sets --lang)."
    ),
    "emulation.setemulatedmedia": (
        "reverts on the next tool call — set it again in the same call as "
        "whatever reads it (no persistent tool for this yet)."
    ),
    "network.setuseragentoverride": (
        "reverts on the next tool call (no persistent tool for this yet)."
    ),
}

_SESSION_SCOPED_PREFIX = (
    "This effect is bound to the CDP session. adb opens a fresh session per tool "
    "call, so it does NOT persist to your next call: "
)


def _session_scoped_note(method: str) -> str | None:
    """A warning for a session-scoped method whose effect won't survive adb's
    per-call model, or None. The whole point of issue #7: setDownloadBehavior
    via cdp_send returns a bare success while silently dropping downloadPath."""
    tail = _SESSION_SCOPED_METHODS.get(method.strip().lower())
    return _SESSION_SCOPED_PREFIX + tail if tail else None


async def cdp_send(
    tab: Tab,
    method: str,
    params: str | None = None,
) -> dict:
    """Use when: NO tool wraps the CDP call you need — the raw-protocol escape
    hatch. Reach for a specific tool first (`page_goto`, `window_set`,
    `page_screenshot`, ...); they steer correct usage and shape the return.
    Returns `{result}` — whatever the CDP method returned, verbatim.

    Heads-up on session-scoped overrides: an effect like
    `Browser.setDownloadBehavior` or the `Emulation.*` overrides is bound to the
    CDP session, and adb opens a fresh session per tool call — so it will NOT
    survive to your next call (often gone before a follow-up click), even though
    CDP reports success. When you call one, the return carries a `warning`
    naming the durable tool to use instead (`download_link`, `window_set`,
    `browser_start --timezone/--geo/--locale`). Don't read a bare
    `{"result": null}` as a lasting change.

    Args:
        tab: Tab instance
        method: CDP method name (e.g., "Browser.getVersion", "DOM.getDocument")
        params: JSON string of parameters. Keys may be the CDP-native camelCase
            copied straight from the protocol docs (`deviceScaleFactor`) or the
            snake_case the Python bindings use (`device_scale_factor`) — both
            are accepted.

    Returns:
        dict with `result` (or `error`), plus a `warning` when the method's
        effect is session-scoped and won't persist to the next call.

    Failure:
        The command errored. Common causes: an unknown `method` (must be
        `Domain.command`, e.g. `Page.navigate` — check the domain and command
        spelling); a parameter name that doesn't exist on that method (casing
        is normalized, but the name must be real — check the CDP docs); or a
        value of the wrong type. The error text names the offending method or
        parameter — read it rather than guessing.
    """
    # Parse params if provided
    parsed_params = {}
    if params:
        parsed_params = json.loads(params)

    # The CDP docs (and everyone copying from them) use camelCase; the vendored
    # bindings take snake_case kwargs. Normalize top-level keys so a verbatim
    # `{"deviceScaleFactor": 1}` doesn't blow up as an unexpected-kwarg error.
    parsed_params = {camel_to_snake(k): v for k, v in parsed_params.items()}

    # Create CDP command generator
    cdp_cmd = _get_cdp_command(method, parsed_params)

    # Send CDP command
    result = await tab.send(cdp_cmd)

    # Try to serialize result
    try:
        json.dumps(result)
        out: dict = {"result": result}
    except (TypeError, ValueError):
        out = {"result": str(result)}

    # Fail loud on a silently-non-persistent effect: a session-scoped override
    # (setDownloadBehavior, Emulation.* overrides) applied here evaporates when
    # this call's session closes, but CDP returns a bare success. Say so, and
    # name the durable tool — so `{"result": null}` isn't mistaken for a lasting
    # change (issue #7).
    note = _session_scoped_note(method)
    if note:
        out["warning"] = note
    return out
