#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-13 04:28:57

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 8/8 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Start real Chrome -> authenticated approval -> independent HTTP child announces its bound port -> refuse bridge disconnect -> verify HTTP service/PID -> reconnect original Chrome -> one submission
  ✅ Start real Chrome -> authenticated approval -> suspend its owned process -> structured metadata/reconnect failure -> resume -> same page -> one submission
  ✅ Start headless -> login -> user approval -> disconnect -> reconnect -> submit -> restart -> reject stale session
  ✅ Persist login/installed extension -> explicit extension launch -> approve -> disconnect -> reconnect same tab/profile -> submit -> explicit owned restart -> authenticated root -> reject stale input -> owned close
  ✅ Existing logged-in Chrome -> connect -> human-side UI approval -> reject unauthorized restart -> reconnect -> submit -> disconnect -> inspect sentinel
  ✅ Discover help -> request unavailable profile -> inspect unsupported -> start correct CDP -> reject mode mutation -> approve and submit once -> blocked URL reports navigation error -> reconnect same session and inspect state without replay
  ✅ Login -> trusted popup open -> stop/start worker -> same session -> trusted consent -> close owned child -> observe parent server state
  ✅ Configured profile -> launch with zero wait -> retain PID -> connect same launched process -> verify extension nonce matches actual process arguments -> authenticated approval -> submit once -> owned close

Uncovered workflows: None
"""

# Standard library imports
import os

# Third-party imports
import pytest

# Skill-specific imports
from tests.integration.browser_lifecycle_support import LifecycleCLI, LifecycleServer

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


def test_foreign_bridge_listener_is_preserved(lifecycle):
    """
    Real scenario: Reject an unrelated HTTP service on the bridge port and preserve the original Chrome

    Workflow: Start real Chrome -> authenticated approval -> independent HTTP child announces its bound port -> refuse bridge disconnect -> verify HTTP service/PID -> reconnect original Chrome -> one submission

    User problem: Disconnect must never kill an unrelated listener or its hosting process when the port does not identify an adb bridge.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    lifecycle.foreign_bridge_listener()


def test_unavailable_cdp_identity_recovers_without_input_replay(lifecycle):
    """
    Real scenario: Report unavailable identity on a suspended real Chrome, then resume the same page

    Workflow: Start real Chrome -> authenticated approval -> suspend its owned process -> structured metadata/reconnect failure -> resume -> same page -> one submission

    User problem: A temporarily unresponsive Chrome must return a transient failure while preserving launch details and completed server actions.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    lifecycle.unavailable_cdp_identity()


def test_owned_cdp_reconnect_and_explicit_restart(lifecycle):
    """
    Real scenario: Approve once, reconnect the same page, submit once, then explicitly restart

    Workflow: Start headless -> login -> user approval -> disconnect -> reconnect -> submit -> restart -> reject stale session

    User problem: An agent must preserve page/login identity and avoid duplicate server actions while recovering control; restart must be separate.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    lifecycle.owned_cdp()


def test_real_extension_installed_profile_start_disconnect_reconnect(
    lifecycle, configured_lifecycle_profile, installed_lifecycle_mode
):
    """
    Real scenario: Launch and explicitly restart a persistently installed extension profile without loading flags or a CDP port

    Workflow: Persist login/installed extension -> explicit extension launch -> approve -> disconnect -> reconnect same tab/profile -> submit -> explicit owned restart -> authenticated root -> reject stale input -> owned close

    User problem: Reuse the real profile's authenticated browser state and release/recover control without repeating a server submission.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    lifecycle.installed_extension(
        configured_lifecycle_profile, installed_lifecycle_mode
    )


def test_real_extension_existing_chrome_preserves_user_tabs(
    lifecycle, configured_lifecycle_profile
):
    """
    Real scenario: Connect an existing Chrome and continue a user's trusted action in the same automation tab

    Workflow: Existing logged-in Chrome -> connect -> human-side UI approval -> reject unauthorized restart -> reconnect -> submit -> disconnect -> inspect sentinel

    User problem: Connecting and recovering must preserve browser PID/profile, the dedicated page and unrelated user tabs.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    lifecycle.existing_extension(configured_lifecycle_profile)


def test_unsupported_modes_do_not_launch_or_replay(lifecycle):
    """
    Real scenario: Explain missing extension and unsupported attached headless without substituting a browser

    Workflow: Discover help -> request unavailable profile -> inspect unsupported -> start correct CDP -> reject mode mutation -> approve and submit once -> blocked URL reports navigation error -> reconnect same session and inspect state without replay

    User problem: A model needs accurate failure reasons and an explicit recovery decision, never an implicit transport/profile switch.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    lifecycle.unsupported()


async def test_real_extension_worker_recovery_with_oauth_child(
    lifecycle, live_extension
):
    """
    Real scenario: Keep profile/session and OAuth child across a worker interruption

    Workflow: Login -> trusted popup open -> stop/start worker -> same session -> trusted consent -> close owned child -> observe parent server state

    User problem: An extension worker must recover the same parent and OAuth tab without losing profile identity or replaying consent.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    await lifecycle.worker_oauth(live_extension)


def test_real_extension_delayed_handshake_preserves_ownership(
    lifecycle, configured_lifecycle_profile
):
    """
    Real scenario: Recover control after an explicit launch outlasts its handshake deadline

    Workflow: Configured profile -> launch with zero wait -> retain PID -> connect same launched process -> verify extension nonce matches actual process arguments -> authenticated approval -> submit once -> owned close

    User problem: A slow handshake must preserve the real browser and its recorded ownership without launching a second process.

    Data flow:
      1. inline code operation
    """
    # Step 1: Execute operation
    lifecycle.delayed_extension(configured_lifecycle_profile)


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert LifecycleCLI is not None
    assert LifecycleServer is not None
