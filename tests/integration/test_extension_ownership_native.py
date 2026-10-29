#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-29 15:37:13

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 1/1 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Authenticate dedicated main page -> preserve unrelated tab -> click Chrome Cancel through native X11 -> refuse input -> close revoked main -> restart worker -> compare real CLI connect/reconnect/navigation/new-tab errors and stored event time -> invoke native extension shortcut -> fresh visible blank page and new session in same profile -> fence old drivers -> read authenticated HTTP state without submitting -> keep unrelated tab and healthy action idempotent

Uncovered workflows: None
"""

# Standard library imports
import os

# Third-party imports
import pytest

# Skill-specific imports
from tests.integration.extension_ownership_support import (
    navigation_journey,
    cancellation_journey,
)

pytestmark = [
    pytest.mark.extension_native,
    pytest.mark.skipif(
        not os.environ.get("AI_DEV_BROWSER_OWNERSHIP_NATIVE"),
        reason="Requires isolated X11 Chrome with xdotool; enabled in native CI step",
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


async def test_real_extension_native_consent_revocation(live_extension, tmp_path):
    """
    Real scenario: Honor real Chrome native debugger cancellation across reconnect and worker restart

    Workflow: Authenticate dedicated main page -> preserve unrelated tab -> click Chrome Cancel through native X11 -> refuse input -> close revoked main -> restart worker -> compare real CLI connect/reconnect/navigation/new-tab errors and stored event time -> invoke native extension shortcut -> fresh visible blank page and new session in same profile -> fence old drivers -> read authenticated HTTP state without submitting -> keep unrelated tab and healthy action idempotent

    User problem: A user's explicit cancellation must never be undone by automatic recovery or implicit page creation.

    Data flow:
      1. Click real native Cancel, close and restart, then explicitly authorize through Chrome and inspect same-profile authenticated read and screenshots
    """
    # Step 1: Click real native Cancel, close and restart, then explicitly authorize through Chrome and inspect same-profile authenticated read and screenshots
    await cancellation_journey(live_extension, tmp_path)


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert navigation_journey is not None
    assert cancellation_journey is not None
