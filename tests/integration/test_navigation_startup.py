#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-24 04:56:22

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 5/5 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Start actual Chrome with a held initial response -> startup timeout retains process and owned target -> release response -> reconnect same session and target -> one GET and one trusted submission
  ✅ Launch actual Chrome -> arrange an early startup page -> finish browser_start -> first owned navigation held by HTTP -> independent early page navigates to blank -> release one request -> correct owned page -> trusted typing and one submission
  ✅ Launch actual Chrome with URL -> independent early page exists -> prepare blank owned page -> hold its single initial HTTP request -> early page finishes to blank -> release response -> startup returns parsed owned destination -> trusted typing and one submission
  ✅ Own Chrome target -> hold first HTTP request -> competing owned driver navigates -> real ERR_ABORTED -> inspect URL and readiness -> verify destination DOM -> helper dispatched only once
  ✅ Own Chrome target -> hold first request -> actual competing redirect to wrong page -> ERR_ABORTED -> read-only inspection -> failure -> exactly one helper request

Uncovered workflows: None
"""

# Standard library imports
import os

# Third-party imports
import pytest

# Skill-specific imports
from tests.integration.navigation_startup_support import (
    startup_race_journey,
    startup_target_journey,
)

# Integration guard: allow CI to opt-out with SKIP_INTEGRATION=1
SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    """Skip if SKIP_INTEGRATION is set."""
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set — skipping integration tests")


async def test_real_chrome_initial_document_timeout_preserves_owned_page(
    tmp_path, monkeypatch, startup_mode
):
    """
    Real scenario: Keep the owned page when the initial HTTP document exceeds the startup budget

    Workflow: Start actual Chrome with a held initial response -> startup timeout retains process and owned target -> release response -> reconnect same session and target -> one GET and one trusted submission

    User problem: A temporary empty document must not be reported ready or cause startup navigation to be replayed.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await startup_target_journey(
        tmp_path, monkeypatch, startup_mode, with_url=True, slow_initial=True
    )


async def test_real_chrome_startup_target_first_navigation(
    tmp_path, monkeypatch, startup_mode
):
    """
    Real scenario: Keep the first navigation on the owned page while an early startup page finishes

    Workflow: Launch actual Chrome -> arrange an early startup page -> finish browser_start -> first owned navigation held by HTTP -> independent early page navigates to blank -> release one request -> correct owned page -> trusted typing and one submission

    User problem: An early Chrome startup page must not cancel or replace the first application navigation.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await startup_target_journey(tmp_path, monkeypatch, startup_mode)


async def test_real_chrome_startup_target_explicit_url(
    tmp_path, monkeypatch, startup_mode
):
    """
    Real scenario: Load the requested startup URL once on the owned page

    Workflow: Launch actual Chrome with URL -> independent early page exists -> prepare blank owned page -> hold its single initial HTTP request -> early page finishes to blank -> release response -> startup returns parsed owned destination -> trusted typing and one submission

    User problem: Chrome startup must keep the requested URL and target identity without replaying navigation.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await startup_target_journey(tmp_path, monkeypatch, startup_mode, with_url=True)


async def test_real_chrome_startup_navigation_cancellation(tmp_path):
    """
    Real scenario: Inspect the actual destination after Chrome reports an aborted startup navigation

    Workflow: Own Chrome target -> hold first HTTP request -> competing owned driver navigates -> real ERR_ABORTED -> inspect URL and readiness -> verify destination DOM -> helper dispatched only once

    User problem: A startup navigation race must not trigger blind replay or hide a wrong destination.

    Data flow:
      1. Force the cancellation using actual HTTP and Chrome/CDP actors
    """
    # Step 1: Force the cancellation using actual HTTP and Chrome/CDP actors
    await startup_race_journey(tmp_path)


async def test_real_chrome_startup_wrong_destination_is_refused(tmp_path):
    """
    Real scenario: Keep a cancelled navigation failed when Chrome settles on another page

    Workflow: Own Chrome target -> hold first request -> actual competing redirect to wrong page -> ERR_ABORTED -> read-only inspection -> failure -> exactly one helper request

    User problem: Navigation recovery must not hide a wrong destination or dispatch input again.

    Data flow:
      1. Force a real abort to another destination and verify refusal without replay
    """
    # Step 1: Force a real abort to another destination and verify refusal without replay
    await startup_race_journey(tmp_path, accepted=False)


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert startup_race_journey is not None
    assert startup_target_journey is not None
