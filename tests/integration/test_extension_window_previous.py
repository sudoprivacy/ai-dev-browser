#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-20 09:13:27

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 1/1 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Load the released extension -> connect through the current CLI -> compare actual loaded and bundled versions -> request window restore -> preserve unsupported refusal, versions and ordinary reload guidance

Uncovered workflows: None
"""

# Standard library imports
import os

# Third-party imports
import pytest

# Skill-specific imports
from tests.integration.extension_window_support import previous_extension_journey

pytestmark = pytest.mark.extension_previous

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


async def test_real_extension_previous_window_update_guidance(live_extension, tmp_path):
    """
    Real scenario: Diagnose an unchanged released extension through the current Python CLI

    Workflow: Load the released extension -> connect through the current CLI -> compare actual loaded and bundled versions -> request window restore -> preserve unsupported refusal, versions and ordinary reload guidance

    User problem: Updating Python must not imply that the user's running Chrome extension supports new window operations.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await previous_extension_journey(live_extension, tmp_path)


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert previous_extension_journey is not None
