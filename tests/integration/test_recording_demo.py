#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-08 12:17:29

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 4/4 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Record -> move across CLI -> click -> type -> drag -> resize -> submit -> decode visible cursor and click feedback
  ✅ Record page-only -> interact at ordinary speed -> save without cursor graphics
  ✅ Connect extension -> record -> move -> click -> type -> stop -> decode GIF
  ✅ Record -> open another tab -> fill -> return -> fill -> stop -> fill again

Uncovered workflows: None
"""

# Standard library imports
import os

# Third-party imports
import pytest

# Skill-specific imports
from tests.integration.recording_demo_support import (
    run_demo_journey,
    run_extension_demo,
    run_opt_out,
    run_recording_lifecycle,
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


def test_recording_demo_cli_journey(cli, recording_browser, tmp_path):
    """
    Real scenario: Record -> move across CLI -> click -> type -> drag -> resize -> submit -> decode visible cursor and click feedback

    Workflow: Record -> move across CLI -> click -> type -> drag -> resize -> submit -> decode visible cursor and click feedback

    User problem: Share an understandable recording of actual browser actions, with an explicit page-only opt out.

    Data flow:
      1. Run real browser input across independently invoked CLI tools and inspect the saved GIF
    """
    # Step 1: Run real browser input across independently invoked CLI tools and inspect the saved GIF
    run_demo_journey(cli, recording_browser, tmp_path)


def test_recording_demo_opt_out(cli, recording_browser, tmp_path):
    """
    Real scenario: Record page-only -> interact at ordinary speed -> save without cursor graphics

    Workflow: Record page-only -> interact at ordinary speed -> save without cursor graphics

    User problem: Share an understandable recording of actual browser actions, with an explicit page-only opt out.

    Data flow:
      1. Run real browser input across independently invoked CLI tools and inspect the saved GIF
    """
    # Step 1: Run real browser input across independently invoked CLI tools and inspect the saved GIF
    run_opt_out(cli, recording_browser, tmp_path)


async def test_recording_demo_real_extension(live_extension, tmp_path, monkeypatch):
    """
    Real scenario: Record through the bundled extension -> restore cursor across SDK connections -> trusted click -> paced typing -> inspect GIF feedback

    Workflow: Connect extension -> record -> move -> click -> type -> stop -> decode GIF

    User problem: The normal-browser extension must produce the same understandable demo as direct CDP automation.

    Data flow:
      1. Use an isolated real bundled extension and inspect actual input events and GIF pixels
    """
    # Step 1: Use an isolated real bundled extension and inspect actual input events and GIF pixels
    monkeypatch.setenv("AI_DEV_BROWSER_RECORDING_DIR", str(tmp_path / "recordings"))
    await run_extension_demo(live_extension, tmp_path)


def test_recording_demo_lifecycle(cli, recording_browser, tmp_path):
    """
    Real scenario: Record one tab -> ordinary input on another tab -> paced input on recorded tab -> stop -> ordinary input restored

    Workflow: Record -> open another tab -> fill -> return -> fill -> stop -> fill again

    User problem: Demo pacing must not spread to other tabs or remain active after recording finishes.

    Data flow:
      1. Run the recording lifecycle in real independent CLI processes
    """
    # Step 1: Run the recording lifecycle in real independent CLI processes
    run_recording_lifecycle(cli, recording_browser, tmp_path)


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert callable(run_demo_journey)
    assert callable(run_opt_out)
    assert callable(run_extension_demo)
    assert callable(run_recording_lifecycle)
