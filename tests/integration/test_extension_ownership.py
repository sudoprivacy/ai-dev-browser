#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-19 10:14:14

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 5/5 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Own consent page -> reconnect -> trusted submit once -> follow Chrome-proven result -> reject unrelated same-origin tab -> restart worker -> fresh CLI read -> structured missing-page failure
  ✅ Own consent page -> reconnect -> trusted submit once -> follow Chrome-proven result -> reject unrelated same-origin tab -> restart worker -> fresh CLI read -> structured missing-page failure
  ✅ Own consent page -> reconnect -> trusted submit once -> follow Chrome-proven result -> reject unrelated same-origin tab -> restart worker -> fresh CLI read -> structured missing-page failure
  ✅ Own consent page -> reconnect -> trusted submit once -> follow Chrome-proven result -> reject unrelated same-origin tab -> restart worker -> fresh CLI read -> structured missing-page failure
  ✅ Own consent page -> reconnect -> trusted submit once -> follow Chrome-proven result -> reject unrelated same-origin tab -> restart worker -> fresh CLI read -> structured missing-page failure

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


async def test_real_extension_ownership_same(live_extension, tmp_path):
    """
    Real scenario: Keep proven automation ownership through same navigation

    Workflow: Own consent page -> reconnect -> trusted submit once -> follow Chrome-proven result -> reject unrelated same-origin tab -> restart worker -> fresh CLI read -> structured missing-page failure

    User problem: Navigation must preserve control without replaying completed submissions or exposing unrelated tabs.

    Data flow:
      1. Exercise same workflow with server receipts and real extension
    """
    # Step 1: Exercise same workflow with server receipts and real extension
    await navigation_journey(live_extension, tmp_path, "same")


async def test_real_extension_ownership_cross(live_extension, tmp_path):
    """
    Real scenario: Keep proven automation ownership through cross navigation

    Workflow: Own consent page -> reconnect -> trusted submit once -> follow Chrome-proven result -> reject unrelated same-origin tab -> restart worker -> fresh CLI read -> structured missing-page failure

    User problem: Navigation must preserve control without replaying completed submissions or exposing unrelated tabs.

    Data flow:
      1. Exercise cross workflow with server receipts and real extension
    """
    # Step 1: Exercise cross workflow with server receipts and real extension
    await navigation_journey(live_extension, tmp_path, "cross")


async def test_real_extension_ownership_child(live_extension, tmp_path):
    """
    Real scenario: Keep proven automation ownership through child navigation

    Workflow: Own consent page -> reconnect -> trusted submit once -> follow Chrome-proven result -> reject unrelated same-origin tab -> restart worker -> fresh CLI read -> structured missing-page failure

    User problem: Navigation must preserve control without replaying completed submissions or exposing unrelated tabs.

    Data flow:
      1. Exercise child workflow with server receipts and real extension
    """
    # Step 1: Exercise child workflow with server receipts and real extension
    await navigation_journey(live_extension, tmp_path, "child")


async def test_real_extension_ownership_noopener(live_extension, tmp_path):
    """
    Real scenario: Keep proven automation ownership through noopener navigation

    Workflow: Own consent page -> reconnect -> trusted submit once -> follow Chrome-proven result -> reject unrelated same-origin tab -> restart worker -> fresh CLI read -> structured missing-page failure

    User problem: Navigation must preserve control without replaying completed submissions or exposing unrelated tabs.

    Data flow:
      1. Exercise noopener workflow with server receipts and real extension
    """
    # Step 1: Exercise noopener workflow with server receipts and real extension
    await navigation_journey(live_extension, tmp_path, "noopener")


async def test_real_extension_ownership_close_parent(live_extension, tmp_path):
    """
    Real scenario: Keep proven automation ownership through close-parent navigation

    Workflow: Own consent page -> reconnect -> trusted submit once -> follow Chrome-proven result -> reject unrelated same-origin tab -> restart worker -> fresh CLI read -> structured missing-page failure

    User problem: Navigation must preserve control without replaying completed submissions or exposing unrelated tabs.

    Data flow:
      1. Exercise close-parent workflow with server receipts and real extension
    """
    # Step 1: Exercise close-parent workflow with server receipts and real extension
    await navigation_journey(live_extension, tmp_path, "close-parent")


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert navigation_journey is not None
    assert cancellation_journey is not None
