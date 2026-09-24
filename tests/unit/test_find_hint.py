"""find_by_text's miss hint names only the causes present on THIS page.

The bug: the hint always said "Cross-origin iframes are not scanned" even when
the document had no iframe — pointing at a cause that can't apply. It now probes
the page and mentions an iframe / <svg>/<canvas> only when one is present.
"""

from __future__ import annotations

import pytest

from ai_dev_browser.core.elements import _not_found_hint


class _FakeTab:
    def __init__(self, counts):
        self._counts = counts

    async def evaluate(self, expr, *a, **k):
        return self._counts


@pytest.mark.asyncio
async def test_hint_mentions_iframe_only_when_present():
    h = await _not_found_hint(_FakeTab({"iframe": 2, "drawn": 0}))
    assert "iframe" in h.lower() and "svg" not in h.lower()


@pytest.mark.asyncio
async def test_hint_mentions_svg_only_when_present():
    h = await _not_found_hint(_FakeTab({"iframe": 0, "drawn": 6}))
    assert "svg" in h.lower() and "iframe" not in h.lower()


@pytest.mark.asyncio
async def test_hint_names_neither_on_a_plain_page():
    h = await _not_found_hint(_FakeTab({"iframe": 0, "drawn": 0}))
    assert "iframe" not in h.lower() and "svg" not in h.lower()
    assert "not found" in h.lower()  # still gives the base advice


@pytest.mark.asyncio
async def test_hint_survives_a_failed_probe():
    class Boom:
        async def evaluate(self, *a, **k):
            raise RuntimeError("probe failed")

    h = await _not_found_hint(Boom())
    assert "not found" in h.lower() and "iframe" not in h.lower()
