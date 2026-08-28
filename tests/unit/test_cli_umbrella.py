"""Tests for the umbrella `browser` CLI (ai_dev_browser.cli).

These exercise discovery/grouping, error classification → exit codes, and
the argparse tree without needing a live browser.
"""

import json
import subprocess
import sys

import pytest

from ai_dev_browser import cli
from ai_dev_browser.tools._generate import INTERNAL, _discover_tools


def test_tree_covers_every_discovered_tool():
    tree = cli._build_tree()
    reachable = {m["name"] for verbs in tree.values() for m in verbs.values()}
    discovered = {t["name"] for t in _discover_tools()}
    assert reachable == discovered, discovered ^ reachable


def test_no_internal_or_constant_leaks():
    tree = cli._build_tree()
    reachable = {m["name"] for verbs in tree.values() for m in verbs.values()}
    # No INTERNAL infra functions
    assert not (reachable & INTERNAL)
    # No constants (UPPER or CapWords names from core.__all__)
    import ai_dev_browser.core as core

    consts = {n for n in core.__all__ if n[:1].isupper()}
    assert not (reachable & consts)


def test_noun_verb_uniqueness():
    tree = cli._build_tree()
    for noun, verbs in tree.items():
        assert len(verbs) == len(set(verbs)), noun


@pytest.mark.parametrize(
    "name,noun,verb",
    [
        ("browser_start", "session", "start"),
        ("page_goto", "page", "goto"),
        ("page_wait_element", "page", "wait-element"),
        ("click_by_text", "click", "text"),
        ("click_by_html_id", "click", "html-id"),
        ("find_by_xpath", "find", "xpath"),
        ("type_by_ref", "type", "ref"),
        ("focus_by_ref", "element", "focus"),
        ("js_evaluate", "js", "evaluate"),
        ("cdp_send", "cdp", "send"),
        ("window_set", "window", "set"),
        ("download", "download", "run"),
    ],
)
def test_grouping(name, noun, verb):
    assert cli._derive_group(name) == (noun, verb)


@pytest.mark.parametrize(
    "message,code,retryable",
    [
        ("Element not found", cli.EXIT_NOT_FOUND, False),
        ("Failed to connect to Chrome on 127.0.0.1:9222", cli.EXIT_NOT_FOUND, True),
        ("operation timed out after 30s", cli.EXIT_TRANSIENT, True),
        ("unauthorized: login required", cli.EXIT_AUTH, False),
        ("rate limit exceeded", cli.EXIT_RATE_LIMIT, True),
        ("port already in use", cli.EXIT_CONFLICT, False),
        ("missing required argument", cli.EXIT_VALIDATION, False),
        ("something weird happened", cli.EXIT_TRANSIENT, True),
    ],
)
def test_classify(message, code, retryable):
    got_code, got_retryable, hint = cli._classify(message)
    assert got_code == code
    assert got_retryable == retryable
    assert hint


def test_normalize_result_shapes():
    assert cli._normalize_result(True, "clicked") == {"clicked": True}
    assert cli._normalize_result(False, "clicked") == {"error": "Operation failed"}
    assert cli._normalize_result([1, 2], "x") == [1, 2]
    assert cli._normalize_result({"a": 1}, "x") == {"a": 1}
    assert cli._normalize_result("hi", "value") == {"value": "hi"}


def _run(args):
    """Run the installed-equivalent CLI as a subprocess (stdout non-TTY)."""
    return subprocess.run(
        [sys.executable, "-m", "ai_dev_browser.cli", *args],
        capture_output=True,
        text=True,
    )


def test_list_emits_json_when_piped():
    proc = _run(["--list"])
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["count"] == len({t["name"] for t in _discover_tools()})


def test_missing_required_flag_exit_2():
    proc = _run(["page", "goto"])
    assert proc.returncode == 2  # argparse validation


def test_login_no_interactive_fails_fast_exit_7():
    # Non-TTY auto-enables --no-interactive, so login must refuse, not hang.
    proc = _run(["login", "interactive", "--url", "https://example.com"])
    assert proc.returncode == cli.EXIT_AUTH
    err = json.loads(proc.stderr)
    assert err["error"]["code"] == cli.EXIT_AUTH


def test_noun_without_verb_exit_2():
    proc = _run(["page"])
    assert proc.returncode == cli.EXIT_VALIDATION
    assert "verbs:" in proc.stderr


def test_browser_or_tab_flag_not_exposed():
    # tab_* tools take `browser_or_tab` as the injected first param; it must
    # not surface as a required CLI flag.
    proc = _run(["tab", "list", "--help"])
    assert proc.returncode == 0
    assert "--browser-or-tab" not in proc.stdout


def test_top_level_flags_not_passed_as_kwargs(monkeypatch):
    # session list takes no params; ensure list_commands/top_json/etc. don't
    # leak into the core call. Runs without a browser (lifecycle tool).
    proc = _run(["session", "list"])
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["count"] == 0
