"""Host-owned journal and input helpers; capabilities are explicit test fixtures."""

import asyncio
import hashlib
import json
import os
from pathlib import Path

from ai_dev_browser.remote.session import BrowserSession

QUERY = "保留录制 incremental request"
SECRET = "INCREMENTAL_PASSWORD_FIXTURE_SECRET"  # pragma: allowlist secret


async def current_fixture():
    return None


class Journal:
    def __init__(self, path, *, lose_input_ack=False):
        self.path = Path(path)
        self.lose_input_ack = lose_input_ack
        self.calls = []

    async def append(self, identity, event):
        assert identity == "retained-original-recording"
        row = {"recordingId": identity, "event": event}
        raw = (json.dumps(row, ensure_ascii=False) + "\n").encode()
        assert SECRET.encode() not in raw
        self.calls.append((identity, event["seq"]))

        def write():
            with self.path.open("ab") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())

        await asyncio.to_thread(write)
        if self.lose_input_ack and event["kind"] in {"input", "change"}:
            raise ConnectionError("fixture acknowledgement lost after actual fsync")

    def rows(self):
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
        ]


async def start_recording(browser, http, origin, journal, terminal):
    session = BrowserSession(browser, http)
    await session.state(before_effect=current_fixture)
    await session.control.take("original-human", before_effect=current_fixture)
    page = await session._connect_page()
    target = session.target_id

    async def authorize_frame(actual_target, frame, context, unique, source_origin):
        assert actual_target == target and source_origin == origin
        assert frame and type(context) is int and unique
        return current_fixture

    async def persist(payload):
        # The original terminal publisher is separate from the event journal.
        terminal.append(payload)

    status = await session.start_recording(
        "original-human",
        session.control.epoch,
        session.control.target_epoch,
        "retained-original-recording",
        before_effect=current_fixture,
        authorize_frame=authorize_frame,
        before_read=current_fixture,
        persist=persist,
        event_sink=journal.append,
    )
    assert status["status"] == "recording" and terminal == []
    return session, page


async def click(session, page, selector):
    point = await page.js(
        f"(()=>{{const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}}}})()"
    )
    await session.action(
        "original-human",
        session.control.epoch,
        session.control.target_epoch,
        {"kind": "input", "input": {"kind": "click", **point}},
        before_effect=current_fixture,
    )


async def type_text(session, value):
    await session.action(
        "original-human",
        session.control.epoch,
        session.control.target_epoch,
        {"kind": "input", "input": {"kind": "text", "text": value}},
        before_effect=current_fixture,
    )


async def submit_original_form(session, page):
    await click(session, page, "#query")
    await type_text(session, QUERY)
    await click(session, page, "#password")
    await type_text(session, SECRET)
    await click(session, page, "#submit")


def inspect_journal(path):
    rows = Journal(path).rows()
    events = [row["event"] for row in rows]
    assert rows and all(
        row["recordingId"] == "retained-original-recording" for row in rows
    )
    assert [event["seq"] for event in events] == list(range(1, len(rows) + 1))
    assert SECRET not in json.dumps(rows, ensure_ascii=False)
    assert any(event.get("value") == QUERY for event in events)
    assert any(
        event.get("redacted") and event["kind"] in {"input", "change"}
        for event in events
    )
    assert all(event["targetId"] and event["frameId"] for event in events)
    return {
        "recordingId": rows[0]["recordingId"],
        "events": len(rows),
        "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "sequential": True,
        "privateValuesAbsent": True,
    }
