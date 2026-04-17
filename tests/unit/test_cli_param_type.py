"""Regression tests for _cli._get_param_type.

Targets the PEP 604 (`int | None`) vs classic `Union[int, None]` gap that
silently coerced every --port argument to str and crashed every tool
accepting an `int | None` / `float | None` parameter (browser_start,
browser_stop, node_id-based tools).
"""

from typing import Literal, Union

from ai_dev_browser._cli import _get_param_type


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
