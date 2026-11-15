"""Build a reviewable draft from existing events; never execute or install it."""

from __future__ import annotations

import copy
import json
from typing import Any

from .models import PrivacySettings
from .privacy import redact_event
from .semantic import SemanticProcessor
from .skill_generator import SkillGenerator


def build_recording_draft(
    recording_id: str,
    events: list[dict[str, Any]],
    *,
    privacy: PrivacySettings | None = None,
    skill_name: str | None = None,
) -> dict[str, Any]:
    """Use when you have recorded events; return parameterized steps and a Skill draft.

    This pure transformation has no browser, filesystem or host authority.
    Capture, current target resolution and explicit replay remain separate
    checked operations; recorded descriptors never authorize an effect.
    """
    if (
        not isinstance(recording_id, str)
        or not 1 <= len(recording_id.encode("utf-8")) <= 128
        or any(ord(char) < 32 for char in recording_id)
    ):
        raise ValueError("Invalid recording identity")
    if not isinstance(events, list) or len(events) > 10_000:
        raise ValueError("Invalid recording events")
    if privacy is not None and not isinstance(privacy, PrivacySettings):
        raise ValueError("Invalid recording privacy policy")
    if skill_name is not None and not isinstance(skill_name, str):
        raise ValueError("Invalid recording skill name")
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("Invalid recording event")
        if event.get("kind") == "file_selection":
            raise ValueError("Recording requires explicit authorized file binding")
        for key in ("target", "page"):
            if event.get(key) is not None and not isinstance(event[key], dict):
                raise ValueError("Invalid recording descriptor")
    try:
        encoded = json.dumps(events, ensure_ascii=False, allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Invalid recording JSON") from None
    if len(encoded) > 4 * 1024 * 1024:
        raise ValueError("Recording event data is too large")
    policy = privacy or PrivacySettings()
    redacted = [redact_event(copy.deepcopy(event), policy) for event in events]
    steps = SemanticProcessor(recording_id, redacted).process()
    return {
        "steps": steps.model_dump(by_alias=True),
        "skillDraft": SkillGenerator(steps, skill_name=skill_name).generate(),
    }
