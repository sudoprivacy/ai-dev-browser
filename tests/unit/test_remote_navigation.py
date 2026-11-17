"""A navigation barrier only repeats fixed reads of the new document."""

import asyncio

import pytest

from ai_dev_browser.remote.cdp import CDP, BrowserViewError


def test_navigation_process_swap_does_not_read_the_previous_document():
    class Probe(CDP):
        def __init__(self):
            self.probes = 0
            self.reads = 0

        async def call(self, method, params=None, timeout=20):
            assert method == "Page.getFrameTree"
            self.probes += 1
            if self.probes == 1:
                error = BrowserViewError("operation_failed")
                error.details = {
                    "message": "Debugger is not attached to the tab with id: 42."
                }
                raise error
            return {
                "frameTree": {
                    "frame": {"loaderId": "old" if self.probes == 2 else "new"}
                }
            }

        async def js(self, expression):
            assert expression == "document.readyState !== 'loading'"
            self.reads += 1
            return True

    probe = Probe()
    asyncio.run(probe.wait_navigation({"loaderId": "new"}))
    assert probe.probes == 3 and probe.reads == 1


def test_navigation_does_not_retry_unrelated_protocol_failures():
    class Probe(CDP):
        def __init__(self):
            self.probes = 0

        async def call(self, method, params=None, timeout=20):
            self.probes += 1
            error = BrowserViewError("operation_failed")
            error.details = {"message": "Permission denied"}
            raise error

    probe = Probe()
    with pytest.raises(BrowserViewError, match="operation_failed"):
        asyncio.run(probe.wait_navigation({"loaderId": "new"}))
    assert probe.probes == 1


@pytest.mark.parametrize("history_entry", [None, 42])
async def test_empty_navigation_ack_waits_for_actual_reload_or_history_commit(
    history_entry,
):
    committed = asyncio.Event()

    class Probe(CDP):
        def __init__(self):
            self.probes = 0
            self.reads = 0

        async def call(self, method, params=None, timeout=20):
            if method == "Page.getFrameTree":
                self.probes += 1
                if self.probes >= 3:
                    committed.set()
                loader = (
                    "new" if self.probes >= 3 and history_entry is None else "previous"
                )
                return {"frameTree": {"frame": {"loaderId": loader}}}
            assert method == "Page.getNavigationHistory"
            # Native currentIndex may already describe an uncommitted entry.
            return {"currentIndex": 0, "entries": [{"id": 42}]}

        async def js(self, expression):
            assert expression == "document.readyState !== 'loading'"
            self.reads += 1
            assert self.probes >= 3
            return True

    probe = Probe()
    await probe.wait_navigation(
        {},
        previous_loader="previous",
        history_entry=history_entry,
        history_committed=committed if history_entry is not None else None,
    )
    assert probe.probes == 3 and probe.reads == 1
