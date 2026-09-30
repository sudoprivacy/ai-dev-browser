"""Regression tests for _cli._get_param_type.

Targets the PEP 604 (`int | None`) vs classic `Union[int, None]` gap that
silently coerced every --port argument to str and crashed every tool
accepting an `int | None` / `float | None` parameter (browser_start,
browser_stop, node_id-based tools).
"""

from typing import Literal, Union

import pytest

from ai_dev_browser._cli import _generate_parser, _get_param_type


def test_plain_types():
    assert _get_param_type(int) is int
    assert _get_param_type(float) is float
    assert _get_param_type(str) is str


def test_bool_returns_parser_callable():
    parser = _get_param_type(bool)
    assert callable(parser)
    assert parser("true") is True
    assert parser("True") is True
    assert parser("1") is True
    assert parser("yes") is True
    assert parser("false") is False
    assert parser("0") is False


def test_literal_returns_str():
    # Literal values are constrained via argparse `choices`, type stays str.
    assert _get_param_type(Literal["none", "any"]) is str


def test_pep604_union_int_none():
    # The regression: PEP 604 `int | None` used to fall through to str.
    assert _get_param_type(int | None) is int


def test_pep604_union_str_none():
    assert _get_param_type(str | None) is str


def test_pep604_union_float_none():
    assert _get_param_type(float | None) is float


def test_classic_union_int_none():
    # Classic typing.Union still works — make sure fix didn't regress it.
    assert _get_param_type(Union[int, None]) is int


def test_classic_optional_int():
    # typing.Optional[X] == Union[X, None]
    from typing import Optional

    assert _get_param_type(Optional[int]) is int


def test_union_with_no_none_falls_through():
    # int | str has no None — not a simple optional; fall back to str.
    assert _get_param_type(int | str) is str


def test_list_str_returns_str():
    # list[str] → element type is str (nargs handled in parser)
    assert _get_param_type(list[str]) is str


def test_list_int_returns_int():
    assert _get_param_type(list[int]) is int


def test_optional_list_str():
    assert _get_param_type(list[str] | None) is str


def test_dict_returns_json_loads():
    import json

    assert _get_param_type(dict) is json.loads
    assert _get_param_type(dict[str, str]) is json.loads


def test_optional_dict_returns_json_loads():
    import json

    assert _get_param_type(dict[str, str] | None) is json.loads


@pytest.mark.parametrize("hint", [bool | str, str | bool | None, Union[bool, str]])
@pytest.mark.parametrize(
    "value,expected",
    [
        ("True", True),
        ("false", False),
        ("1", True),
        ("0", False),
        ("new", "new"),
        ("old", "old"),
        ("invalid", "invalid"),
    ],
)
def test_boolean_or_named_mode(hint, value, expected):
    parsed = _get_param_type(hint)(value)
    assert parsed == expected
    assert type(parsed) is type(expected)


def test_omitted_boolean_preserves_none_default():
    from ai_dev_browser.core.mouse import mouse_click

    parser = _generate_parser(mouse_click)
    base = ["--x", "1", "--y", "2", "--no-move"]
    assert parser.parse_args(base).human_like is None
    assert parser.parse_args(base + ["--human-like"]).human_like is True
    assert parser.parse_args(base + ["--no-human-like"]).human_like is False
