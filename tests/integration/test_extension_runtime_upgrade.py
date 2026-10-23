#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-23 22:05:18

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 1/1 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Released extension without version reporting -> connect warning and unsupported window -> ordinary extension reload in the same Chrome -> reject old session and preserve original tabs -> verify loaded/bundled match -> restore real window -> trusted neutral-form input and one submission

Uncovered workflows: None
"""

# Standard library imports
import os

# Third-party imports
import pytest

# Skill-specific imports
from tests.integration.extension_runtime_support import runtime_upgrade_journey

pytestmark = pytest.mark.extension_unknown

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


async def test_real_extension_unknown_runtime_upgrade(live_extension, tmp_path, caplog):
    """
    Real scenario: Resolve an unknown released runtime before input without restarting Chrome

    Workflow: Released extension without version reporting -> connect warning and unsupported window -> ordinary extension reload in the same Chrome -> reject old session and preserve original tabs -> verify loaded/bundled match -> restore real window -> trusted neutral-form input and one submission

    User problem: A Python upgrade must reveal an unverified running extension before a login workflow, and ordinary recovery must preserve Chrome and existing tabs without replaying input.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await runtime_upgrade_journey(live_extension, tmp_path, caplog)


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert runtime_upgrade_journey is not None
