"""cdp_send coerces JSON object/array params into the binding's typed classes.

Without this, an array-of-objects param (e.g. setEmulatedMedia's `features`)
reaches the generated binding as plain dicts, which it serializes with
`.to_json()` — raising "'dict' object has no attribute 'to_json'". _coerce_params
rebuilds them from the param's type annotation.
"""

from __future__ import annotations

from ai_dev_browser.cdp import emulation
from ai_dev_browser.core.cdp import _coerce_params, _coerce_value


def test_coerce_list_of_typed_objects():
    params = {"features": [{"name": "prefers-color-scheme", "value": "dark"}]}
    out = _coerce_params(emulation.set_emulated_media, params)
    feats = out["features"]
    assert isinstance(feats, list) and len(feats) == 1
    assert isinstance(feats[0], emulation.MediaFeature)
    assert feats[0].name == "prefers-color-scheme"
    assert feats[0].value == "dark"


def test_coerce_leaves_primitive_params_alone():
    out = _coerce_params(emulation.set_emulated_media, {"media": "print"})
    assert out["media"] == "print"


def test_coerce_value_passthrough_without_annotation():
    assert _coerce_value([1, 2, 3], None) == [1, 2, 3]
    assert _coerce_value("x", None) == "x"


def test_coerce_value_single_object():
    mf = _coerce_value({"name": "a", "value": "b"}, emulation.MediaFeature)
    assert isinstance(mf, emulation.MediaFeature) and mf.name == "a"
