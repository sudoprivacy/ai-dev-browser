"""Exercise fresh native extension identities across consecutive cold launches."""

import hashlib
import json

import pytest

from ai_dev_browser.core import cdp_send


@pytest.fixture(scope="module")
def startup_profiles():
    return set()


@pytest.mark.parametrize("cold_launch", range(8), ids=lambda value: f"cold-{value + 1}")
async def test_real_extension_cold_start_identity(
    live_extension, cold_launch, startup_profiles, request, tmp_path
):
    state = (await live_extension.call(cdp_send, method="AiDevBrowser.debugState"))[
        "result"
    ]
    hello = live_extension.bridge.identity
    profile = state["profileId"]
    assert profile and profile == hello["profile_id"]
    assert profile not in startup_profiles
    startup_profiles.add(profile)
    assert state["sessionId"] and state["sessionId"] == hello["session_id"]
    main = state["mainTabId"]
    assert main is not None and str(main) == hello["automation_target_id"]
    assert state["autoTabs"] == [main] and state["attached"] == [main]
    evidence = {
        "launch": cold_launch + 1,
        "backend": request.node.callspec.params["live_extension"],
        "profileSha256": hashlib.sha256(profile.encode()).hexdigest(),
        "sessionSha256": hashlib.sha256(state["sessionId"].encode()).hexdigest(),
        "mainTabId": main,
        "ownedTabCount": len(state["autoTabs"]),
        "identityMatchesHello": True,
    }
    (tmp_path / "cold-extension-startup-evidence.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
