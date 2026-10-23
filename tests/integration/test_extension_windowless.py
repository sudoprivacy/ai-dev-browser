#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-24 03:04:34

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 1/1 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Actual Chrome with no startup window -> real extension hello must already name its owned target -> CDP first page creation proceeds once -> connect and inspect matching runtime -> neutral form on extension-owned target -> trusted typing and exactly one submission

Uncovered workflows: None
"""

# Standard library imports
import os

# Third-party imports
import pytest

# Skill-specific imports
from tests.integration.extension_window_support import windowless_startup_journey

pytestmark = pytest.mark.extension_windowless

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


async def test_real_extension_windowless_owned_startup(
    live_extension, remote_site, tmp_path
):
    """
    Real scenario: Create the extension-owned window before the first CDP page

    Workflow: Actual Chrome with no startup window -> real extension hello must already name its owned target -> CDP first page creation proceeds once -> connect and inspect matching runtime -> neutral form on extension-owned target -> trusted typing and exactly one submission

    User problem: A connected extension must create its own usable page when Chrome initially has no window.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await windowless_startup_journey(live_extension, remote_site, tmp_path)


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert windowless_startup_journey is not None
