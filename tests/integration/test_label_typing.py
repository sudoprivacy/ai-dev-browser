#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-11-09 15:30:34

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 6/6 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Open app dialog -> resolve Name wrapper -> trusted name and multiline description fills -> fill labelled, placeholder, editable and iframe fields -> one HTTP submission -> inspect rendered result
  ✅ Open form -> focus sentinel -> refuse multi-input wrapper and duplicate names via real CLI -> refuse static text and wrapper ref -> zero events, zero Input commands and no submissions
  ✅ Open app dialog -> resolve Name wrapper -> trusted name and multiline description fills -> fill labelled, placeholder, editable and iframe fields -> one HTTP submission -> inspect rendered result
  ✅ Open form -> focus sentinel -> refuse multi-input wrapper and duplicate names via real CLI -> refuse static text and wrapper ref -> zero events, zero Input commands and no submissions
  ✅ Open app list -> trusted open modal -> discover background search and modal Name -> fill actual Name and Description -> one trusted HTTP submission -> cancel -> refuse six genuine ambiguity cases without input
  ✅ Open app list -> trusted open modal -> discover background search and modal Name -> fill actual Name and Description -> one trusted HTTP submission -> cancel -> refuse six genuine ambiguity cases without input

Uncovered workflows: None
"""

# Standard library imports
import os

# Third-party imports
import pytest

# Skill-specific imports
from tests.integration.label_typing_support import (
    fill_journey,
    refusal_journey,
    modal_journey,
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


async def test_cdp_label_fill(interaction_cdp, tmp_path):
    """
    Real scenario: cdp: resolve field labels and preserve unrelated inputs

    Workflow: Open app dialog -> resolve Name wrapper -> trusted name and multiline description fills -> fill labelled, placeholder, editable and iframe fields -> one HTTP submission -> inspect rendered result

    User problem: A field label must resolve to one real editable field without guessing or typing into containers.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await fill_journey(interaction_cdp, tmp_path)


async def test_cdp_label_refusal(interaction_cdp, tmp_path, caplog):
    """
    Real scenario: cdp: refuse ambiguous labels and noneditable refs before input

    Workflow: Open form -> focus sentinel -> refuse multi-input wrapper and duplicate names via real CLI -> refuse static text and wrapper ref -> zero events, zero Input commands and no submissions

    User problem: A field label must resolve to one real editable field without guessing or typing into containers.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await refusal_journey(interaction_cdp, tmp_path, caplog)


async def test_real_extension_label_fill(live_extension, tmp_path):
    """
    Real scenario: extension: resolve field labels and preserve unrelated inputs

    Workflow: Open app dialog -> resolve Name wrapper -> trusted name and multiline description fills -> fill labelled, placeholder, editable and iframe fields -> one HTTP submission -> inspect rendered result

    User problem: A field label must resolve to one real editable field without guessing or typing into containers.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await fill_journey(live_extension, tmp_path)


async def test_real_extension_label_refusal(live_extension, tmp_path, caplog):
    """
    Real scenario: extension: refuse ambiguous labels and noneditable refs before input

    Workflow: Open form -> focus sentinel -> refuse multi-input wrapper and duplicate names via real CLI -> refuse static text and wrapper ref -> zero events, zero Input commands and no submissions

    User problem: A field label must resolve to one real editable field without guessing or typing into containers.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await refusal_journey(live_extension, tmp_path, caplog)


async def test_cdp_modal_label(interaction_cdp, tmp_path, caplog):
    """
    Real scenario: cdp: distinguish exact field labels from background substrings

    Workflow: Open app list -> trusted open modal -> discover background search and modal Name -> fill actual Name and Description -> one trusted HTTP submission -> cancel -> refuse six genuine ambiguity cases without input

    User problem: The original Name label must beat an unrelated background substring without guessing between genuine duplicate fields.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await modal_journey(interaction_cdp, tmp_path, caplog)


async def test_real_extension_modal_label(live_extension, tmp_path, caplog):
    """
    Real scenario: real_extension: distinguish exact field labels from background substrings

    Workflow: Open app list -> trusted open modal -> discover background search and modal Name -> fill actual Name and Description -> one trusted HTTP submission -> cancel -> refuse six genuine ambiguity cases without input

    User problem: The original Name label must beat an unrelated background substring without guessing between genuine duplicate fields.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await modal_journey(live_extension, tmp_path, caplog)


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert callable(fill_journey)
    assert callable(refusal_journey)
    assert callable(modal_journey)
