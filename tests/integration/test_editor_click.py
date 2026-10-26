#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-25 21:18:42

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 10/10 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Load actual Monaco with a controlled application restoring the original document -> discover proxy -> request replacement plus Enter -> observe full model mismatch -> one editor edit and one application restoration -> no typing fallback or Enter
  ✅ Load real editor with application restoration -> discover -> replace plus Enter -> verify mismatch -> no second write and no Enter
  ✅ Load official Monaco with an existing long document -> discover proxy ref -> fill seven-scope JSON through the real CLI -> verify one full model edit -> fill long JSON through Python -> preserve second editor and ordinary fields
  ✅ Load actual editor with private model API -> discover proxy -> request real CLI replacement and Enter -> nonzero unsupported result -> no input or model change
  ✅ Discover collapsed child -> refuse ref/text/id/xpath and actual CLI clicks without input -> refuse overlay -> expand real menu -> one trusted navigation -> one ordinary non-navigation action
  ✅ Discover the real proxy textarea -> replace existing JSON -> verify entire long model -> preserve independent editor -> verify ordinary input/textarea
  ✅ Discover real Monaco without a public model API -> request replacement and Enter -> refuse without document changes -> inspect full model and ledger
  ✅ Discover hidden link -> reject ref/text clicks and overlay without events -> expand menu -> one trusted navigation -> one visible action without navigation
  ✅ Discover actual iframe button -> click ref and observe one trusted event -> discover open and closed shadow buttons -> one trusted event each -> click iframe by html id -> inspect exact event ledger and rendered screenshot
  ✅ Discover actual iframe button -> click ref and observe one trusted event -> discover open and closed shadow buttons -> one trusted event each -> click iframe by html id -> inspect exact event ledger and rendered screenshot

Uncovered workflows: None
"""

# Standard library imports
import os

# Third-party imports
import pytest

# Skill-specific imports
from tests.integration.editor_click_support import (
    editor_journey,
    navigation_journey,
    rejected_editor_journey,
    nested_click_journey,
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


async def test_real_extension_editor_rejection_no_replay(
    live_extension, interaction_site, tmp_path
):
    """
    Real scenario: Stop after the application rejects a full document replacement

    Workflow: Load actual Monaco with a controlled application restoring the original document -> discover proxy -> request replacement plus Enter -> observe full model mismatch -> one editor edit and one application restoration -> no typing fallback or Enter

    User problem: Verification failure must not replay a destructive write or submit the wrong document.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await rejected_editor_journey(live_extension, interaction_site, tmp_path)


async def test_cdp_editor_rejection_no_replay(
    interaction_cdp, interaction_site, tmp_path
):
    """
    Real scenario: Preserve rejected editor content without replay in CDP

    Workflow: Load real editor with application restoration -> discover -> replace plus Enter -> verify mismatch -> no second write and no Enter

    User problem: Both transports must stop on an application-rejected full document edit.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await rejected_editor_journey(interaction_cdp, interaction_site, tmp_path)


async def test_real_extension_monaco_exact_document(
    live_extension, interaction_site, tmp_path
):
    """
    Real scenario: Replace a real Monaco document without retrying its input proxy

    Workflow: Load official Monaco with an existing long document -> discover proxy ref -> fill seven-scope JSON through the real CLI -> verify one full model edit -> fill long JSON through Python -> preserve second editor and ordinary fields

    User problem: A proxy textarea must never cause duplicate JSON documents or a false verified result.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await editor_journey(live_extension, interaction_site, tmp_path)


async def test_real_extension_private_editor_refused(
    live_extension, interaction_site, tmp_path
):
    """
    Real scenario: Preserve an editor whose full model is unavailable

    Workflow: Load actual editor with private model API -> discover proxy -> request real CLI replacement and Enter -> nonzero unsupported result -> no input or model change

    User problem: Unknown editor models require an explicit unsupported result rather than destructive fallback or accidental submission.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await editor_journey(live_extension, interaction_site, tmp_path, private_api=True)


async def test_real_extension_collapsed_navigation(
    live_extension, interaction_site, tmp_path
):
    """
    Real scenario: Refuse hidden and covered nav targets, then activate the visible item once

    Workflow: Discover collapsed child -> refuse ref/text/id/xpath and actual CLI clicks without input -> refuse overlay -> expand real menu -> one trusted navigation -> one ordinary non-navigation action

    User problem: A hidden link must not receive a verified success from unrelated focus changes or synthetic fallback.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await navigation_journey(live_extension, interaction_site, tmp_path)


async def test_cdp_monaco_exact_document(interaction_cdp, interaction_site, tmp_path):
    """
    Real scenario: Replace real Monaco JSON using standalone Chrome

    Workflow: Discover the real proxy textarea -> replace existing JSON -> verify entire long model -> preserve independent editor -> verify ordinary input/textarea

    User problem: Both transports must share safe verified-fill behavior.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await editor_journey(interaction_cdp, interaction_site, tmp_path)


async def test_cdp_private_editor_refused(interaction_cdp, interaction_site, tmp_path):
    """
    Real scenario: Refuse an unverifiable Monaco model in standalone Chrome

    Workflow: Discover real Monaco without a public model API -> request replacement and Enter -> refuse without document changes -> inspect full model and ledger

    User problem: Standalone mode must not corrupt editor proxies or submit unverifiable content.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await editor_journey(interaction_cdp, interaction_site, tmp_path, private_api=True)


async def test_cdp_collapsed_navigation(interaction_cdp, interaction_site, tmp_path):
    """
    Real scenario: Check actual visible hit targets in standalone Chrome

    Workflow: Discover hidden link -> reject ref/text clicks and overlay without events -> expand menu -> one trusted navigation -> one visible action without navigation

    User problem: Hidden geometry and unrelated focus must not produce a verified click receipt.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await navigation_journey(interaction_cdp, interaction_site, tmp_path)


async def test_real_extension_nested_hit_targets(
    live_extension, interaction_site, tmp_path
):
    """
    Real scenario: Preserve trusted clicks in scaled iframes and open/closed shadow roots

    Workflow: Discover actual iframe button -> click ref and observe one trusted event -> discover open and closed shadow buttons -> one trusted event each -> click iframe by html id -> inspect exact event ledger and rendered screenshot

    User problem: Shared hit-target validation must handle real nested documents and shadow roots without refusing valid controls or sending input to another target.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await nested_click_journey(live_extension, interaction_site, tmp_path)


async def test_cdp_nested_hit_targets(interaction_cdp, interaction_site, tmp_path):
    """
    Real scenario: Preserve trusted clicks in scaled iframes and open/closed shadow roots

    Workflow: Discover actual iframe button -> click ref and observe one trusted event -> discover open and closed shadow buttons -> one trusted event each -> click iframe by html id -> inspect exact event ledger and rendered screenshot

    User problem: Shared hit-target validation must handle real nested documents and shadow roots without refusing valid controls or sending input to another target.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await nested_click_journey(interaction_cdp, interaction_site, tmp_path)


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert callable(editor_journey)
    assert callable(navigation_journey)
    assert callable(rejected_editor_journey)
    assert callable(nested_click_journey)
