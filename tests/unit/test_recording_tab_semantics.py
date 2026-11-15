"""Preserve actual recorded target identity across equal URLs/values."""

from ai_dev_browser.record.draft import build_recording_draft


def event(sequence, kind, target_id, page_url, **fields):
    return {
        "seq": sequence,
        "kind": kind,
        "targetId": target_id,
        "page": {"url": page_url},
        **fields,
    }


def test_new_target_at_original_url_remains_a_distinct_new_tab_step():
    url = "https://original.example/form"
    field = {"name": "Query", "role": "textbox", "id": "query"}
    events = [
        event(1, "recorder_installed", "first", url),
        event(2, "input", "first", url, target=field, value="first value"),
        event(3, "page_opened", "second", "about:blank", url="about:blank"),
    ]
    events.extend(
        [
            event(4, "navigation", "second", url, urlAfter=url),
            event(5, "recorder_installed", "second", url),
            event(6, "input", "second", url, target=field, value="second value"),
        ]
    )
    doc = build_recording_draft("original", events)["steps"]
    tabs = [step for step in doc["steps"] if step["kind"] == "new_tab"]
    assert len(tabs) == 1 and tabs[0]["target"]["targetId"] == "second"
    assert [
        step["target"]["targetId"] for step in doc["steps"] if step["kind"] == "fill"
    ] == ["first", "second"]


def test_equal_field_values_on_different_targets_are_not_coalesced():
    first, second = "https://original.example/form", "https://other.example/form"
    field = {"name": "Query", "role": "textbox", "id": "query"}
    events = [
        event(1, "recorder_installed", "first", first),
        event(2, "input", "first", first, target=field, value="same value"),
        event(3, "page_opened", "second", second),
        event(4, "input", "second", second, target=field, value="same value"),
    ]
    doc = build_recording_draft("original", events)["steps"]
    assert [
        step["target"]["targetId"] for step in doc["steps"] if step["kind"] == "fill"
    ] == ["first", "second"]
