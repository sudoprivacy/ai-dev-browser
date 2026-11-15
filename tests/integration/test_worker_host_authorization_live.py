#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-11-16 01:59:07

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 2/2 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Launch -> observe -> edit -> withdraw -> refuse -> restore -> submit -> verify -> stop
  ✅ Connect -> observe -> edit -> withdraw -> refuse -> restore -> submit -> disconnect

Uncovered workflows: None
"""

# Standard library imports
import os

# Third-party imports
import pytest

# Skill-specific imports
from tests.integration.worker_host_authorization_support import (
    host_journey,
    extension_host_journey,
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


async def test_host_wait_revoke_recover_submit_once(tmp_path):
    """
    Real scenario: Host launch waits -> revoke -> explicit launch -> trusted input -> revoke queued/layout/history work -> resume -> one submit -> guarded file upload -> stop

    Workflow: Launch -> observe -> edit -> withdraw -> refuse -> restore -> submit -> verify -> stop

    User problem: A human operation waiting on the browser must not use withdrawn permissions or be resent after recovery.

    Data flow:
      1. Exercise real Worker HTTP, Chrome input and server receipt plus held streaming upload
    """
    # Step 1: Exercise real Worker HTTP, Chrome input and server receipt plus held streaming upload
    await host_journey(tmp_path)


async def test_extension_host_wait_revoke_recover_submit_once(live_extension, tmp_path):
    """
    Real scenario: Connect existing extension -> trusted input -> revoke pending effects -> refuse -> recover on same browser -> one submit -> disconnect

    Workflow: Connect -> observe -> edit -> withdraw -> refuse -> restore -> submit -> disconnect

    User problem: Personal Chrome must enforce the same host assertion without replacing the browser or replaying a rejected input.

    Data flow:
      1. Run production extension connection and managed Worker in a fresh correctly configured process; verify trusted input and one real HTTP receipt
    """
    # Step 1: Run production extension connection and managed Worker in a fresh correctly configured process; verify trusted input and one real HTTP receipt
    await extension_host_journey(live_extension, tmp_path)


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert callable(host_journey)
    assert callable(extension_host_journey)
