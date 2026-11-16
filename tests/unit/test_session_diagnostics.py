"""Real control/read fences; the single page socket and grants are fixtures."""

import asyncio
import base64
import copy
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from ai_dev_browser.remote.control import BrowserControl, ControlError
from ai_dev_browser.remote.session import BrowserSession


async def allowed():
    return None


def png(width=4, height=9):
    stream = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(stream, "PNG")
    return base64.b64encode(stream.getvalue()).decode()


class Page:
    def __init__(self):
        self.disconnected = False
        self.handlers = set()
        self.calls = []
        self.frames = {
            "frame": {
                "id": "root",
                "loaderId": "document-original",
                "url": "https://original.test/",
                "securityOrigin": "https://original.test",
            }
        }
        self.before_return = None
        self.image = png()
        self.size = {"width": 4, "height": 9}

    def add_event_handler(self, handler):
        self.handlers.add(handler)

    def remove_event_handler(self, handler):
        self.handlers.remove(handler)

    def event(self, method):
        for handler in tuple(self.handlers):
            handler(method, {})

    async def call(self, method, params=None):
        self.calls.append((method, copy.deepcopy(params)))
        if method == "Page.getFrameTree":
            result = {"frameTree": copy.deepcopy(self.frames)}
        elif method == "DOM.getDocument":
            result = {
                "root": {
                    "nodeId": 1,
                    "nodeName": "#document",
                    "children": [
                        {
                            "nodeName": "INPUT",
                            "attributes": ["value", "private-original"],
                        }
                    ],
                }
            }
        elif method == "Accessibility.getFullAXTree":
            result = {
                "nodes": [
                    {
                        "nodeId": "ax-original",
                        "role": {"value": "RootWebArea"},
                        "name": {"value": "Original diagnostic"},
                    }
                ]
            }
        elif method == "Page.getLayoutMetrics":
            result = {"cssContentSize": self.size}
        elif method == "Page.captureScreenshot":
            result = {"data": self.image}
        else:
            raise AssertionError(
                "diagnostics attempted a write, input or unrelated command: " + method
            )
        if self.before_return:
            await self.before_return(method)
        return result


class Grants:
    def __init__(self):
        self.permitted = True
        self.requests = []

    async def __call__(self, target, frame):
        self.requests.append((target, copy.deepcopy(frame)))

        async def current():
            if not self.permitted:
                raise PermissionError(
                    "original full DOM/AX/pixels/source projection withdrawn"
                )

        return current


def session():
    page = Page()
    sdk = BrowserSession.__new__(BrowserSession)
    sdk.control = BrowserControl()
    sdk.target_id = "original-target"
    sdk._page = page
    sdk._dialog = None

    async def connect():
        return page

    sdk._connect_page = connect
    return sdk, page, Grants()


async def read(sdk, grants, current=allowed):
    return await sdk.diagnostics(0, 0, before_read=current, authorize_frame=grants)


async def test_same_original_page_full_dom_ax_and_full_height_png_without_control_transfer():
    sdk, page, grants = session()
    sdk.control.state, sdk.control.controller = "human", "original-human"
    before = sdk.control.snapshot()
    result = await read(sdk, grants)
    assert result["activeTargetId"] == "original-target"
    assert result["dom"]["children"][0]["attributes"] == ["value", "private-original"]
    assert result["accessibility"][0]["nodeId"] == "ax-original"
    assert (
        result["screenshot"]["height"] == 9 and result["screenshot"]["fullPage"] is True
    )
    assert result["screenshot"]["data"] == page.image
    assert grants.requests[0][1]["loaderId"] == "document-original"
    assert sdk.control.snapshot() == before and sdk._page is page and not page.handlers
    assert sum(method == "Page.captureScreenshot" for method, _ in page.calls) == 1


@pytest.mark.parametrize("missing", ["before_read", "authorize_frame"])
async def test_missing_actual_read_capability_refuses_before_any_page_read(missing):
    sdk, page, grants = session()
    arguments = {"before_read": allowed, "authorize_frame": grants}
    arguments[missing] = None
    with pytest.raises(ControlError, match="browser_authorization_required"):
        await sdk.diagnostics(0, 0, **arguments)
    assert not page.calls


@pytest.mark.parametrize("kind", ["request", "frame-factory", "frame-assertion"])
async def test_false_or_missing_completion_is_not_read_authority(kind):
    sdk, page, grants = session()

    async def invalid():
        return False

    async def factory(target, facts):
        return None if kind == "frame-factory" else invalid

    with pytest.raises(ControlError, match="invalid_browser_authorization"):
        await read(
            sdk,
            factory if kind != "request" else grants,
            invalid if kind == "request" else allowed,
        )
    assert not any(
        method in {"DOM.getDocument", "Page.captureScreenshot"}
        for method, _ in page.calls
    )
    assert not page.handlers


async def test_all_child_sources_need_original_grant_before_full_page_pixels_or_dom():
    sdk, page, grants = session()
    page.frames["childFrames"] = [
        {
            "frame": {
                "id": "child",
                "loaderId": "foreign-loader",
                "url": "https://foreign.test/private",
                "securityOrigin": "https://foreign.test",
            }
        }
    ]
    requests = []

    async def grant(target, frame):
        requests.append(copy.deepcopy(frame))
        if frame["id"] == "child":
            raise PermissionError("foreign source not granted")
        return allowed

    with pytest.raises(ControlError, match="browser_authorization_denied"):
        await read(sdk, grant)
    assert [f["id"] for f in requests] == ["root", "child"]
    assert requests[1]["path"] == ["https://foreign.test"]
    assert not any(
        method in {"DOM.getDocument", "Page.captureScreenshot"}
        for method, _ in page.calls
    )


async def test_mutating_callback_fact_copy_cannot_replace_original_source_binding():
    sdk, page, _ = session()

    async def grant(target, frame):
        frame["loaderId"] = "replacement"
        frame["path"].append("https://replacement.test")
        return allowed

    result = await read(sdk, grant)
    assert (
        result["frames"][0]["loaderId"] == "document-original"
        and result["frames"][0]["path"] == []
    )


@pytest.mark.parametrize(
    "change",
    ["epoch", "target", "page", "source-event", "loader-without-event", "grant"],
)
async def test_changes_during_actual_snapshot_reply_withhold_original_data(change):
    sdk, page, grants = session()

    async def changed(method):
        if method != "Page.captureScreenshot":
            return
        if change == "epoch":
            sdk.control.epoch += 1
        elif change == "target":
            sdk.target_id = "replacement-target"
        elif change == "page":
            sdk._page = SimpleNamespace(disconnected=False)
        elif change == "source-event":
            # Even same facts after add/remove must not erase an intervening
            # native source invalidation while screenshot bytes were pending.
            page.event("Page.frameAttached")
            page.event("Page.frameDetached")
        elif change == "loader-without-event":
            page.frames["frame"]["loaderId"] = "replacement-loader"
        else:
            grants.permitted = False

    page.before_return = changed
    with pytest.raises(ControlError):
        await read(sdk, grants)
    assert sum(method == "Page.captureScreenshot" for method, _ in page.calls) == 1
    assert not page.handlers


async def test_source_change_during_grant_wait_prevents_dom_or_pixels():
    sdk, page, _ = session()

    async def grant(target, frame):
        page.event("Page.frameNavigated")
        return allowed

    with pytest.raises(ControlError, match="browser_diagnostic_context_changed"):
        await read(sdk, grant)
    assert not any(
        method in {"DOM.getDocument", "Page.captureScreenshot"}
        for method, _ in page.calls
    )


async def test_read_grant_is_checked_after_waiting_for_original_input_barrier():
    sdk, page, grants = session()
    entered, release = asyncio.Event(), asyncio.Event()
    permitted = True

    async def blocked():
        entered.set()
        await release.wait()

    async def current():
        if not permitted:
            raise PermissionError("original read revoked while input drains")

    prior = asyncio.create_task(
        sdk.control.run("ai", 0, 0, blocked, before_effect=allowed)
    )
    await entered.wait()
    pending = asyncio.create_task(read(sdk, grants, current))
    await asyncio.sleep(0)
    permitted = False
    release.set()
    await prior
    with pytest.raises(ControlError, match="browser_authorization_denied"):
        await pending
    assert not page.calls


async def test_cancellation_drains_same_original_screenshot_and_never_retries():
    sdk, page, grants = session()
    entered, release = asyncio.Event(), asyncio.Event()

    async def held(method):
        if method == "Page.captureScreenshot":
            entered.set()
            await release.wait()

    page.before_return = held
    pending = asyncio.create_task(read(sdk, grants))
    try:
        await entered.wait()
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done() and sdk.control._operations.locked()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not sdk.control._operations.locked() and not page.handlers
    assert sum(method == "Page.captureScreenshot" for method, _ in page.calls) == 1


async def test_over_budget_full_page_refuses_instead_of_returning_viewport():
    sdk, page, grants = session()
    page.size = {"width": 100000, "height": 100000}
    with pytest.raises(ControlError, match="browser_diagnostic_too_large"):
        await read(sdk, grants)
    assert not any(method == "Page.captureScreenshot" for method, _ in page.calls)


async def test_viewport_image_cannot_be_mislabeled_as_full_page_diagnostics():
    sdk, page, grants = session()
    page.image = png(4, 3)
    with pytest.raises(ControlError, match="browser_diagnostic_image_invalid"):
        await read(sdk, grants)
    assert not page.handlers
