"""Disposable original recorder process; the parent owns Chrome and its cleanup."""

import argparse
import asyncio
import json
import sys

import aiohttp

from ai_dev_browser.core.connection import BrowserClient
from tests.integration.semantic_event_sink_support import (
    Journal,
    inspect_journal,
    start_recording,
    submit_original_form,
)
from tests.integration.test_remote_view import wait_for


async def record(args):
    browser = await BrowserClient.connect("127.0.0.1", args.port)
    terminal = []
    async with aiohttp.ClientSession() as http:
        journal = Journal(args.journal)
        session, page = await start_recording(
            browser, http, args.origin, journal, terminal
        )
        await submit_original_form(session, page)

        async def rows():
            return journal.rows()

        await wait_for(
            rows, lambda value: any(row["event"]["kind"] == "submit" for row in value)
        )
        result = inspect_journal(args.journal)
        assert terminal == []
        print(json.dumps({"capturedBeforeStop": True, **result}), flush=True)
        # The test terminates this process here, with capture active and NO
        # Stop/terminal publisher. Chrome belongs to the still-live parent.
        await asyncio.to_thread(sys.stdin.readline)
        raise AssertionError("Parent must end the recorder process without Stop")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", required=True)
    parser.add_argument("--read-journal", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--origin")
    args = parser.parse_args()
    if args.read_journal:
        print(json.dumps(inspect_journal(args.journal)), flush=True)
    else:
        asyncio.run(record(args))
