#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-29 15:22:33

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 1/1 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Connect through a real installed extension -> retain an unrelated page -> close the proven main target -> reconnect without creating a page -> compare connect, reconnect and navigation refusals -> preserve the unrelated page

Uncovered workflows: None
"""

# Standard library imports
import os

# Third-party imports
import pytest

# Skill-specific imports
from tests.integration.extension_readiness_support import closed_main_journey

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


async def test_real_extension_closed_main(live_extension, tmp_path):
    """
    Real scenario: Report missing dedicated pages consistently across real CLI operations

    Workflow: Connect through a real installed extension -> retain an unrelated page -> close the proven main target -> reconnect without creating a page -> compare connect, reconnect and navigation refusals -> preserve the unrelated page

    User problem: Bridge liveness must not report a usable connection when its dedicated page is absent.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await closed_main_journey(live_extension, tmp_path)


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert callable(closed_main_journey)
