"""One selected target and control lease for page viewers and agent tools.

The host supplies an already authorized BrowserClient. It authenticates actor
and viewer IDs and keeps raw browser endpoints private. This module owns only
its connections and viewers; disconnecting it never stops Chrome.
"""

import asyncio
import logging
import time
import uuid
from typing import Any

import aiohttp

from ai_dev_browser.core._transport import ProtocolException

from .authorized_page import navigation_cookie
from .cdp import CDP, BrowserViewError
from .control import BrowserControl, ControlError, SharedViewer
from .page import PageDrag, PageView


class BrowserSession:
    def __init__(
        self, browser, http: aiohttp.ClientSession, *, control=None, files=None
    ):
        self.browser = browser
        self.http = http
        self.control = control or BrowserControl()
        self.target_id = browser._automation_target_id
        self._page = None
        self._browser = None
        self._dialog = None
        self.files = files
        self._file_chooser = None
        self._size = (1280, 900)
        self._viewers: set[str] = set()
        self._frame: dict[str, Any] | None = None
        self._frame_time = 0.0
        self._frame_lock = asyncio.Lock()
        self._frame_generation = 0
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

    def file_chooser(self):
        chooser = self._file_chooser
        return {key: chooser[key] for key in ("id", "mode")} if chooser else None

    def _event(self, method, params):
        if method == "Page.javascriptDialogOpening":
            self._dialog = params
        elif method == "Page.javascriptDialogClosed":
            self._dialog = None
        elif method == "Page.fileChooserOpened" and self.files is not None:
            node = params.get("backendNodeId")
            mode = params.get("mode")
            if (
                type(node) is int
                and node > 0
                and mode in ("selectSingle", "selectMultiple")
            ):
                self._file_chooser = {
                    "id": uuid.uuid4().hex,
                    "mode": mode,
                    "node": node,
                }
        elif method in ("Page.frameNavigated", "Page.loadEventFired"):
            self._frame = None
            self._file_chooser = None
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
        self._file_chooser = None
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
        if self.files is not None and not self._dialog:
            # Extension Chrome may replace its debugger attachment during a
            # navigation. Keep this session-scoped setting on the current one.
            # Chrome blocks this command while a native JavaScript dialog is
            # open. Let the controller answer it before configuring uploads.
            await self._page.call(
                "Page.setInterceptFileChooserDialog", {"enabled": True}
            )
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
                "dialog": self._dialog,
                **(
                    {"fileChooser": self.file_chooser()}
                    if self.files is not None
                    else {}
                ),
            }

        return await self.control.run(
            "ai",
            self.control.epoch,
            self.control.target_epoch,
            current,
            observation=True,
        )

    def invalidate_frame(self):
        self._frame_generation += 1
        self._frame = None

    async def drag_view(self, viewer: str, controller, epoch, target_epoch):
        async def prepare():
            if viewer not in self._viewers:
                raise ControlError("browser_viewer_not_attached")
            if self._dialog:
                raise ControlError("browser_dialog_open")
            page = await self._connect_page()
            width, height = await self._dimensions(page)
            return PageDrag(page, width, height)

        return await self.control.run(controller, epoch, target_epoch, prepare)

    async def frame(
        self, viewer: str, epoch: int, target_epoch: int, *, during_drag=False
    ):
        async def capture():
            if viewer not in self._viewers:
                raise ControlError("browser_viewer_not_attached")
            view = await self._view.attach(viewer)
            # Live page input already owns this connection and the write
            # barrier. Only pixel/layout reads may run alongside that press.
            page = self._page if during_drag else await self._connect_page()
            if page is None or page.disconnected:
                raise ControlError("browser_disconnected")
            if (
                self._frame is None
                or time.monotonic() - self._frame_time >= 0.25
                or self._frame["controlEpoch"] != self.control.epoch
                or self._frame["targetEpoch"] != self.control.target_epoch
            ):
                generation = self._frame_generation
                width, height = await self._dimensions(page)
                data = await view.capture(page, dialog=self._dialog)
                if not data:
                    raise ControlError("browser_dialog_requires_response")
                frame = {
                    "data": data,
                    "width": width,
                    "height": height,
                    "controlEpoch": epoch,
                    "targetEpoch": target_epoch,
                }
                self.control._authorize("ai", epoch, target_epoch, True)
                if viewer not in self._viewers:
                    raise ControlError("browser_viewer_not_attached")
                if generation == self._frame_generation:
                    self._frame = frame
                    self._frame_time = time.monotonic()
                return frame
            return self._frame

        async with self._frame_lock:
            if during_drag:
                # Avoid blocking visual feedback behind the held button.
                # This path cannot evaluate JS, select tabs or perform input.
                # Reject a read that crossed a target/lease change, and never
                # stamp its old pixels with the new operation version.
                self.control._authorize("ai", epoch, target_epoch, True)
                frame = await capture()
                self.control._authorize("ai", epoch, target_epoch, True)
                return frame
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
            **({"fileChooser": self.file_chooser()} if self.files is not None else {}),
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

    async def selection(self, controller: str, epoch: int, target_epoch: int):
        """Read only the selected text under the current human input barrier."""

        async def read():
            if self._dialog:
                raise ControlError("browser_dialog_open")
            return await PageView().selection(await self._connect_page())

        return await self.control.run(controller, epoch, target_epoch, read)

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
                    await (await self._connect_page()).call("Page.bringToFront")
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
            if kind == "upload-files":
                chooser = self._file_chooser
                if (
                    self.files is None
                    or not chooser
                    or action.get("chooserId") != chooser["id"]
                ):
                    raise ControlError("browser_file_chooser_changed")
                file_ids = action.get("fileIds")
                if (
                    not isinstance(file_ids, list)
                    or not 1 <= len(file_ids) <= 20
                    or any(not isinstance(value, str) for value in file_ids)
                ):
                    raise ControlError("browser_files_invalid_selection")
                if len(set(file_ids)) != len(file_ids):
                    raise ControlError("browser_files_invalid_selection")
                if chooser["mode"] == "selectSingle" and len(file_ids) != 1:
                    raise ControlError("browser_files_invalid_selection")
                paths = [
                    str(self.files.path(file_id, kind="upload")) for file_id in file_ids
                ]
                await page.call(
                    "DOM.setFileInputFiles",
                    {"backendNodeId": chooser["node"], "files": paths},
                )
                self._file_chooser = None
            elif kind == "input":
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
                navigation = await page.call("Page.navigate", {"url": action["url"]})
                await page.wait_navigation(navigation)
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

    async def open_authorized_page(self, controller, epoch, target_epoch, url, cookie):
        """Install a host session and open a new owned tab under the human barrier."""
        params = navigation_cookie(url, cookie)

        async def perform():
            if self._dialog:
                raise ControlError("browser_dialog_open")
            previous = self.target_id
            browser = await self._connect_browser()
            created = await browser.call(
                "Target.createTarget", {"url": "about:blank", "background": True}
            )
            page = None
            try:
                await self.browser.update_targets()
                await self._select(created["targetId"])
                page = await self._connect_page()
                installed = await page.call("Network.setCookie", params)
                if not installed.get("success"):
                    raise ControlError("browser_authorized_page_failed")
                navigation = await page.call("Page.navigate", {"url": url})
                if navigation.get("errorText"):
                    raise ControlError("browser_authorized_page_failed")
                await page.wait_navigation(navigation)
                document = (await page.call("Page.getFrameTree"))["frameTree"]["frame"]
                if (
                    document.get("url") != url
                    or document.get("mimeType") != "text/html"
                ):
                    raise ControlError("browser_authorized_page_failed")
                await page.call("Page.bringToFront")
                self._frame = None
            except BaseException:
                # Compensate only this handoff and the target we created. Never
                # retry navigation or overwrite an existing user tab.
                if page and not page.disconnected:
                    try:
                        await page.call(
                            "Network.deleteCookies",
                            {
                                "name": params["name"],
                                "url": url,
                                "path": params["path"],
                            },
                        )
                    except (
                        BrowserViewError,
                        aiohttp.ClientError,
                        ConnectionError,
                        TimeoutError,
                    ):
                        logging.getLogger(__name__).warning(
                            "Authorized-page cookie cleanup failed"
                        )
                try:
                    await browser.call(
                        "Target.closeTarget", {"targetId": created["targetId"]}
                    )
                    tabs = await self._refresh()
                    if previous in {tab["id"] for tab in tabs}:
                        await self._select(previous)
                except (
                    BrowserViewError,
                    aiohttp.ClientError,
                    ConnectionError,
                    TimeoutError,
                ):
                    logging.getLogger(__name__).warning(
                        "Authorized-page target cleanup failed"
                    )
                raise

        return await self.control.run(controller, epoch, target_epoch, perform)

    async def agent_command(
        self, epoch: int, target_epoch: int, method: str, params: dict, *, frame=None
    ):
        """Trusted host-only agent command. Arbitrary evaluation counts as a write."""

        async def perform():
            self._frame = None
            page = await self._connect_page()
            if frame is None:
                return await page.call(method, params)
            tab = next(
                (
                    tab
                    for tab in self.browser.tabs
                    if str(tab.target.target_id) == self.target_id
                ),
                None,
            )
            if tab is None:
                raise ControlError("browser_target_closed")

            def command():
                return (yield {"method": method, "params": params})

            # Native flat session IDs belong to the connection that attached
            # them. Resolve and execute on the same SDK Tab, inside the shared
            # input barrier; never accept a caller-supplied session ID.
            try:
                try:
                    session = await tab.frame_session(frame)
                except ValueError:
                    raise ControlError("invalid_browser_frame") from None
                return await tab.send(command(), session_id=session, timeout=20)
            except ProtocolException as error:
                mapped = BrowserViewError("operation_failed")
                mapped.details = (
                    error.args[0]
                    if error.args and isinstance(error.args[0], dict)
                    else {"message": str(error)}
                )
                raise mapped from error

        return await self.control.run("ai", epoch, target_epoch, perform)

    async def follow_foreground(self, controller: str, epoch: int, target_epoch: int):
        """Follow a native tab selection made by the authorized human viewer.

        Managed extension profiles expose their isolated tabs by machine policy.
        Ordinary extension Chrome continues to expose only its automation tabs.
        This is a human operation, including any focus probe on standalone CDP.
        """

        async def select():
            tabs = await self._refresh()
            if self.browser.transport == "extension":
                browser = await self._connect_browser()
                active = await browser.call("AiDevBrowser.getActiveTarget")
                target = active.get("targetId")
                if target in {tab["id"] for tab in tabs}:
                    await self._select(target)
            elif not self._dialog:
                focused = []
                for tab in self.browser.tabs:
                    ws = await self.http.ws_connect(tab._connection.websocket_url)
                    page = CDP(ws)
                    try:
                        result = await page.call(
                            "Runtime.evaluate",
                            {
                                "expression": "document.visibilityState === 'visible'",
                                "returnByValue": True,
                            },
                        )
                        if result.get("result", {}).get("value") is True:
                            focused.append(str(tab._target.target_id))
                    finally:
                        await page.close()
                if len(focused) == 1:
                    await self._select(focused[0])

        return await self.control.run(controller, epoch, target_epoch, select)

    async def close(self):
        for viewer in list(self._viewers):
            await self.detach(viewer)
        if self._page:
            await self._page.close()
        if self._browser:
            await self._browser.close()
