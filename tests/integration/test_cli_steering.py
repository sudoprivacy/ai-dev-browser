#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-19 17:24:24

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 2/2 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Actual tool help -> start Chrome -> trusted approval -> invalid storage call -> returned hint -> valid storage -> missing cookies -> save/load -> stale ref -> discover/current ref -> unmatched URL wait -> one trusted submit -> inspect final pixels
  ✅ Own HTTP page -> Python batch write -> observed read -> matching CLI read -> CLI paired write -> reload -> persisted Python read

Uncovered workflows: None
"""

# Standard library imports
import os

# Third-party imports
import pytest

# Skill-specific imports
from tests.integration.cli_steering_support import (
    steering_recovery_journey,
    extension_storage_journey,
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


def test_real_cli_recovery_preserves_one_browser_and_submission(lifecycle):
    """
    Real scenario: Recover from invalid inputs, missing cookie files and stale refs without repeating a trusted action

    Workflow: Actual tool help -> start Chrome -> trusted approval -> invalid storage call -> returned hint -> valid storage -> missing cookies -> save/load -> stale ref -> discover/current ref -> unmatched URL wait -> one trusted submit -> inspect final pixels

    User problem: An agent needs actionable failure hints while preserving the session and avoiding duplicate user actions.

    Data flow:
      1. Exercise the real CLI, Chrome, HTTP ledger and saved screenshot
    """
    # Step 1: Exercise the real CLI, Chrome, HTTP ledger and saved screenshot
    steering_recovery_journey(lifecycle)


async def test_real_extension_storage_core_and_cli_match(live_extension, tmp_path):
    """
    Real scenario: Use real extension storage through Python and fresh CLI calls on the same origin

    Workflow: Own HTTP page -> Python batch write -> observed read -> matching CLI read -> CLI paired write -> reload -> persisted Python read

    User problem: A correctly selected storage tool must actually work and confirm values consistently across transports and APIs.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await extension_storage_journey(live_extension, tmp_path)


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert steering_recovery_journey is not None
    assert extension_storage_journey is not None
