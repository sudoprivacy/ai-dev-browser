#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-20 09:02:21

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 1/1 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Neutral form -> minimize the owned window -> restore and inspect real visibility -> cover only the owned window -> refuse mouse and keyboard before dispatch -> uncover -> submit once with trusted input -> inspect final screenshot

Uncovered workflows: None
"""

# Standard library imports
import os

# Third-party imports
import pytest

# Skill-specific imports
import sys
from tests.integration.extension_window_support import window_visibility_journey

pytestmark = [
    pytest.mark.extension_native,
    pytest.mark.extension_occlusion,
    pytest.mark.skipif(
        sys.platform != "win32",
        reason="Requires the owned Windows native occlusion fixture",
    ),
]

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


async def test_real_extension_window_restore_and_hidden_input(live_extension, tmp_path):
    """
    Real scenario: Restore an owned Chrome window and withhold input under real native occlusion

    Workflow: Neutral form -> minimize the owned window -> restore and inspect real visibility -> cover only the owned window -> refuse mouse and keyboard before dispatch -> uncover -> submit once with trusted input -> inspect final screenshot

    User problem: An ordinary profile must support window controls and preserve an actionable hidden-page refusal without claiming that native focus proves visibility.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await window_visibility_journey(live_extension, tmp_path)


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert window_visibility_journey is not None
