"""page_pdf physical-length parsing — the unit conversion that keeps a print
trim exact. CDP printToPDF takes inches only; `_to_inches` converts a unit
suffix once, in one place, and fails loud on a bad value."""

from __future__ import annotations

import pytest

from ai_dev_browser.core.page import _PAPER_PRESETS, _to_inches


def test_to_inches_converts_every_unit():
    assert _to_inches("3.5in", "x") == pytest.approx(3.5)
    assert _to_inches("90mm", "x") == pytest.approx(90 / 25.4)
    assert _to_inches("21cm", "x") == pytest.approx(21 / 2.54)
    assert _to_inches("72pt", "x") == pytest.approx(1.0)
    assert _to_inches("96px", "x") == pytest.approx(1.0)
    # a bare number (or numeric string) is inches — CDP's native unit
    assert _to_inches(8.5, "x") == 8.5
    assert _to_inches("8.5", "x") == pytest.approx(8.5)
    assert _to_inches(None, "x") is None
    # whitespace + case tolerant
    assert _to_inches("  90 MM ", "x") == pytest.approx(90 / 25.4)


def test_to_inches_fails_loud():
    # a bad size must raise, never silently render the wrong trim
    with pytest.raises(ValueError, match="unknown unit"):
        _to_inches("90furlong", "paper_width")
    with pytest.raises(ValueError, match="cannot parse length"):
        _to_inches("wide", "paper_width")


def test_every_preset_parses():
    for name, (w, h) in _PAPER_PRESETS.items():
        assert _to_inches(w, "w") > 0 and _to_inches(h, "h") > 0, name
    # the metric business card is exactly 90x54 mm
    assert _to_inches(_PAPER_PRESETS["card-cn"][0], "w") == pytest.approx(90 / 25.4)
    assert _to_inches(_PAPER_PRESETS["card-cn"][1], "h") == pytest.approx(54 / 25.4)
