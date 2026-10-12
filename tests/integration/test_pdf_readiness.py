#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-13 05:35:53

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 3/3 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Real Chrome CLI launch -> navigation without waiting -> pending real HTTP stylesheet -> print document CSS size -> inspect actual vector PDF and loaded same page -> owned stop
  ✅ Real Chrome CLI launch -> pending 140x80mm stylesheet -> request card-cn -> inspect actual 90x54mm vector PDF -> verify injected rule removed -> owned stop
  ✅ Real Chrome CLI launch -> pending real stylesheet -> request 90mm x 54mm -> inspect MediaBox and reported trim -> same ready page without temporary style -> owned stop

Uncovered workflows: None
"""

# Standard library imports
import os

# Third-party imports
import pytest

# Skill-specific imports
from tests.integration.pdf_readiness_support import verify_pdf_readiness

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


def test_document_page_size_waits_for_stylesheet(tmp_path):
    """
    Real scenario: Print the document's 90x54mm card while its stylesheet is pending

    Workflow: Real Chrome CLI launch -> navigation without waiting -> pending real HTTP stylesheet -> print document CSS size -> inspect actual vector PDF and loaded same page -> owned stop

    User problem: Printing a still-loading stylesheet silently creates a Letter PDF instead of the document's declared physical size.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    verify_pdf_readiness(tmp_path, "document")


def test_preset_page_size_waits_for_stylesheet(tmp_path):
    """
    Real scenario: Apply the 90x54mm preset after the document's different print stylesheet loads

    Workflow: Real Chrome CLI launch -> pending 140x80mm stylesheet -> request card-cn -> inspect actual 90x54mm vector PDF -> verify injected rule removed -> owned stop

    User problem: The requested exact preset must win after document styles load, with no silently rounded fallback.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    verify_pdf_readiness(tmp_path, "preset")


def test_explicit_units_wait_for_stylesheet(tmp_path):
    """
    Real scenario: Print exact explicit metric units after real pending styles complete

    Workflow: Real Chrome CLI launch -> pending real stylesheet -> request 90mm x 54mm -> inspect MediaBox and reported trim -> same ready page without temporary style -> owned stop

    User problem: An explicit physical trim must survive slow page loading and report the dimensions that actually landed.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    verify_pdf_readiness(tmp_path, "units")


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert callable(verify_pdf_readiness)
