"""One selected target and control lease for page viewers and agent tools.

The host supplies an already authorized BrowserClient. It authenticates actor
and viewer IDs and keeps raw browser endpoints private. This module owns only
its connections and viewers; disconnecting it never stops Chrome.
"""

import logging
import time
from typing import Any

import aiohttp

from .cdp import CDP
from .control import BrowserControl, ControlError, SharedViewer
from .page import PageView


class BrowserSession:
    def __init__(self, browser, http: aiohttp.ClientSession, *, control=None):
        self.browser = browser
        self.http = http
        self.control = control or BrowserControl()
        self.target_id = browser._automation_target_id
        self._page = None
        self._browser = None
        self._dialog = None
        self._size = (1280, 900)
        self._viewers: set[str] = set()
        self._frame: dict[str, Any] | None = None
        self._frame_time = 0.0
        self._view = SharedViewer(self._create_view, self._close_view)

    async def _create_view(self):
        return PageView()

    async def _close_view(self, _view):
        self._frame = None

    async def attach(self, viewer: str):
        await self._view.attach(viewer)
        self._viewers.add(viewer)

    async def detach(self, viewer: str):
        self._viewers.discard(viewer)
        await self._view.detach(viewer)

    def _event(self, method, params):
        if method == "Page.javascriptDialogOpening":
            self._dialog = params
        elif method == "Page.javascriptDialogClosed":
            self._dialog = None
        elif method in ("Page.frameNavigated", "Page.loadEventFired"):
            self._frame = None
        elif method == "Inspector.detached":
            logging.getLogger(__name__).warning("Browser debugger detached: %s", params)
            self._frame = None

    async def _refresh(self):
        await self.browser.update_targets()
        tabs = [
            {
                "id": str(tab._target.target_id),
                "title": tab._target.title,
                "url": tab._target.url,
            }
            for tab in self.browser.tabs
        ]
        if self.target_id not in {tab["id"] for tab in tabs}:
            await self._select(tabs[0]["id"] if tabs else None)
        return tabs

    async def _select(self, target_id):
        if target_id == self.target_id:
            return
        if self._page:
            await self._page.close()
            self._page = None
        self.target_id = target_id
        self._dialog = None
        self._frame = None
        self.control.change_target()

    async def _connect_page(self):
        if not self.target_id:
            raise ControlError("browser_target_required")
        if self._page is None:
            tab = next(
                (
                    tab
                    for tab in self.browser.tabs
                    if str(tab._target.target_id) == self.target_id
                ),
                None,
            )
            if tab is None:
                raise ControlError("browser_target_closed")
            ws = await self.http.ws_connect(tab._connection.websocket_url)
            self._page = CDP(ws, self._event)
            await self._page.call("Page.enable")
        # A lost input socket is not silently reconnected/replayed.
        if self._page.disconnected:
            raise ControlError("browser_disconnected")
        return self._page

    async def _connect_browser(self):
        if self._browser is None:
            ws = await self.http.ws_connect(self.browser.connection.websocket_url)
            self._browser = CDP(ws)
        return self._browser

    async def _dimensions(self, page):
        if self._dialog:
            return self._size
        metrics = await page.call("Page.getLayoutMetrics")
        viewport = metrics.get("cssLayoutViewport", metrics.get("layoutViewport", {}))
        self._size = int(viewport["clientWidth"]), int(viewport["clientHeight"])
        return self._size

    async def state(self):
        # Refresh can discover an externally closed target, so construct the
        # snapshot after refreshing, not before it.
        async def current():
            tabs = await self._refresh()
            return {
                **self.control.snapshot(),
                "activeTargetId": self.target_id,
                "tabs": tabs,
            }

        return await self.control.run(
            "ai",
            self.control.epoch,
            self.control.target_epoch,
            current,
            observation=True,
        )

    async def frame(self, viewer: str, epoch: int, target_epoch: int):
        async def capture():
            if viewer not in self._viewers:
                raise ControlError("browser_viewer_not_attached")
            view = await self._view.attach(viewer)
            page = await self._connect_page()
            if (
                self._frame is None
                or time.monotonic() - self._frame_time >= 0.25
                or self._frame["controlEpoch"] != self.control.epoch
                or self._frame["targetEpoch"] != self.control.target_epoch
            ):
                width, height = await self._dimensions(page)
                data = await view.capture(page, dialog=self._dialog)
                if not data:
                    raise ControlError("browser_dialog_requires_response")
                self._frame = {
                    "data": data,
                    "width": width,
                    "height": height,
                    "controlEpoch": self.control.epoch,
                    "targetEpoch": self.control.target_epoch,
                }
                self._frame_time = time.monotonic()
            return self._frame

        return await self.control.run(
            "ai", epoch, target_epoch, capture, observation=True
        )

    async def _observe(self):
        tabs = await self._refresh()
        page = await self._connect_page()
        if self._dialog:
            raise ControlError("browser_dialog_requires_response")
        width, height = await self._dimensions(page)
        tree = await page.call("Accessibility.getFullAXTree")
        # A return always captures current pixels, even with no viewer open.
        view = PageView()
        data = await view.capture(page, dialog=self._dialog)
        return {
            "activeTargetId": self.target_id,
            "tabs": tabs,
            "accessibility": tree.get("nodes", []),
            "dialog": self._dialog,
            "frame": {
                "data": data,
                "width": width,
                "height": height,
                "controlEpoch": self.control.epoch,
                "targetEpoch": self.control.target_epoch,
            },
        }

    async def observe(self, epoch: int, target_epoch: int):
        return await self.control.run(
            "ai", epoch, target_epoch, self._observe, observation=True
        )

    async def take(self, controller: str, epoch: int, target_epoch: int):
        if epoch != self.control.epoch or target_epoch != self.control.target_epoch:
            raise ControlError("stale_browser_operation")
        return await self.control.take(controller)

    async def give_back(self, controller: str, epoch: int, target_epoch: int):
        if epoch != self.control.epoch or target_epoch != self.control.target_epoch:
            raise ControlError("stale_browser_operation")
        return await self.control.give_back(controller, self._observe)

    async def action(self, actor: str, epoch: int, target_epoch: int, action: dict):
        async def perform():
            self._frame = None
            kind = action["kind"]
            if kind in ("new-tab", "select-tab", "close-tab"):
                browser = await self._connect_browser()
                tabs = await self._refresh()
                if kind == "new-tab":
                    created = await browser.call(
                        "Target.createTarget", {"url": "about:blank"}
                    )
                    await self.browser.update_targets()
                    await self._select(created["targetId"])
                else:
                    target = action["targetId"]
                    if target not in {tab["id"] for tab in tabs}:
                        raise ControlError("browser_target_closed")
                    if kind == "select-tab":
                        await self._select(target)
                        await (await self._connect_page()).call("Page.bringToFront")
                    else:
                        await browser.call("Target.closeTarget", {"targetId": target})
                        await self._refresh()
                return
            page = await self._connect_page()
            if kind == "input":
                width, height = await self._dimensions(page)
                if not await PageView().input(
                    page,
                    action["input"],
                    width=width,
                    height=height,
                    dialog=self._dialog,
                ):
                    raise ControlError("invalid_browser_input")
            elif kind == "navigate":
                if not isinstance(action.get("url"), str) or not action[
                    "url"
                ].startswith(("http://", "https://")):
                    raise ControlError("invalid_browser_url")
                await page.call("Page.navigate", {"url": action["url"]})
            elif kind == "reload":
                await page.call("Page.reload")
            elif kind in ("back", "forward"):
                history = await page.call("Page.getNavigationHistory")
                index = history["currentIndex"] + (-1 if kind == "back" else 1)
                if 0 <= index < len(history["entries"]):
                    await page.call(
                        "Page.navigateToHistoryEntry",
                        {"entryId": history["entries"][index]["id"]},
                    )
            else:
                raise ControlError("invalid_browser_action")

        return await self.control.run(actor, epoch, target_epoch, perform)

    async def agent_command(
        self, epoch: int, target_epoch: int, method: str, params: dict
    ):
        """Trusted host-only agent command. Arbitrary evaluation counts as a write."""

        async def perform():
            self._frame = None
            return await (await self._connect_page()).call(method, params)

        return await self.control.run("ai", epoch, target_epoch, perform)

    async def close(self):
        for viewer in list(self._viewers):
            await self.detach(viewer)
        if self._page:
            await self._page.close()
        if self._browser:
            await self._browser.close()
