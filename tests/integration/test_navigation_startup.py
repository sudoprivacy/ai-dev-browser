#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-19 14:18:18

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 2/2 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Own Chrome target -> hold first HTTP request -> competing owned driver navigates -> real ERR_ABORTED -> inspect URL and readiness -> verify destination DOM -> helper dispatched only once
  ✅ Own Chrome target -> hold first request -> actual competing redirect to wrong page -> ERR_ABORTED -> read-only inspection -> failure -> exactly one helper request

Uncovered workflows: None
"""

# Standard library imports
import os

# Third-party imports
import pytest

# Skill-specific imports
from tests.integration.navigation_startup_support import startup_race_journey

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
