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

from ai_dev_browser.core._transport import MAX_SIZE, ProtocolException

from .authorized_page import navigation_cookie
from .cdp import CDP, BrowserViewError
from .commands import _Commands
from .control import (
    BrowserControl,
    ControlError,
    SharedViewer,
    check_effect_authorization,
)
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
        self._recording = None
        self._downloads_ready = False
        self._host_input = None

    async def _create_view(self):
        return PageView()

    async def _close_view(self, _view):
        self._frame = None

    async def attach(self, viewer: str, *, before_effect=None):
        await self._view.attach(viewer, before_effect=before_effect)
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
            if self._recording:
                await self._recording.detach()
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
            ws = await self.http.ws_connect(
                tab._connection.websocket_url, max_msg_size=MAX_SIZE
            )
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
        if self._recording:
            await self._recording.attach(self.target_id, self._page)
        return self._page

    def recording_scopes(self):
        return self._recording.capture.source_scopes() if self._recording else []

    async def start_recording(
        self,
        actor,
        epoch,
        target_epoch,
        recording_id,
        *,
        before_effect,
        authorize_frame,
        before_read,
        persist,
        reconcile=None,
        privacy=None,
    ):
        """Use to capture actions on this session; returns recording metadata.

        Capture follows the selected target and uses the existing page connection.
        SDK input waits for current document admission. For a viewer GIF, choose
        page_record_start. This operation does not acquire input control.

        Args:
            actor: Original authenticated recording owner.
            epoch: Current control version.
            target_epoch: Current selected-target version.
            recording_id: Original recording identity retained through completion.
            before_effect: Current capture assertion; returns None or raises.
            authorize_frame: Current assertion factory for each native document.
            before_read: Current assertion covering the recording and all sources.
            persist: Host writer that returns None after durable persistence.
            reconcile: Host reader proving that exact original write committed.
            privacy: mask-sensitive (default), mask-all, or none.

        Returns:
            Capture and storage metadata. Durable completion is confirmed by Stop.

        Failure:
            Refuses missing capabilities before registration. Retain an existing
            unfinished recording and finish or reconcile its original outcome.
        """
        try:
            from ..record.models import PrivacySettings
            from ..record.session import SessionRecording
        except ImportError:
            raise ControlError("browser_recording_not_installed") from None
        # Validate every required capability before any page registration.
        recording = SessionRecording(
            recording_id,
            actor,
            before_capture=before_effect,
            authorize_frame=authorize_frame,
            before_read=before_read,
            persist=persist,
            reconcile=reconcile,
            privacy=PrivacySettings(input_policy=privacy or "mask-sensitive"),
        )

        async def start():
            if self._recording and self._recording.phase != "saved":
                raise ControlError("browser_recording_pending")
            page = await self._connect_page()
            await check_effect_authorization(before_effect)
            self.control._authorize(actor, epoch, target_epoch, True)
            self._recording = recording
            await recording.attach(self.target_id, page)
            await check_effect_authorization(before_effect)
            self.control._authorize(actor, epoch, target_epoch, True)
            return recording.status()

        return await self.control.run(
            actor,
            epoch,
            target_epoch,
            start,
            observation=True,
            before_effect=before_effect,
        )

    async def stop_recording(
        self,
        actor,
        epoch,
        target_epoch,
        *,
        before_effect,
        before_read,
        reconcile=None,
        generate_steps=True,
        skill_name=None,
    ):
        """Use to finish the original recording; confirms storage after the host ACK.

        Flushes admitted final input, compiles a reviewable draft and waits for
        the original host save. Returns metadata without events or parameter
        values. Repeated Stop never repeats that persistence call.

        Args:
            actor: Original authenticated recording owner.
            epoch: Current control version.
            target_epoch: Current selected-target version.
            before_effect: Current assertion admitting this Stop.
            before_read: Current assertion permitting its outcome metadata.
            reconcile: Authorized reader proving the exact original write exists.
            generate_steps: Whether the first Stop requests steps and a Skill draft.
            skill_name: Optional draft name fixed by the first Stop.

        Failure:
            An uncertain write keeps its original identity. Reconcile that write
            through Stop before starting a new recording; do not resend its save.
        """
        if before_effect is None:
            raise ControlError("browser_authorization_required")
        if self._recording is None:
            raise ControlError("browser_recording_not_started")

        async def stop():
            return await self._recording.finish(
                actor,
                before_read=before_read,
                reconcile=reconcile,
                generate_steps=generate_steps,
                skill_name=skill_name,
            )

        return await self.control.run(
            actor,
            epoch,
            target_epoch,
            stop,
            observation=True,
            before_effect=before_effect,
        )

    async def recording_status(self, actor, epoch, target_epoch, *, before_effect):
        """Use to inspect recording metadata; does not read events or take control.

        Returns capture/storage status for the original owner, or None if no
        recording exists. Requires current read authority and session versions.
        """
        if before_effect is None:
            raise ControlError("browser_authorization_required")

        async def read():
            if not self._recording:
                return None
            self._recording.assert_owner(actor)
            result = self._recording.status()
            await check_effect_authorization(before_effect)
            return result

        return await self.control.run(
            actor,
            epoch,
            target_epoch,
            read,
            observation=True,
            before_effect=before_effect,
        )

    async def _connect_browser(self):
        if self._browser is None:
            ws = await self.http.ws_connect(
                self.browser.connection.websocket_url, max_msg_size=MAX_SIZE
            )
            self._browser = CDP(ws)
        return self._browser

    async def _configure_downloads(
        self, actor, epoch, target_epoch, *, before_effect=None
    ):
        # An explicit files store belongs to this host-owned isolated profile.
        # Personal extension sessions have no store; retain their settings.
        if (
            self.files is None
            or self._downloads_ready
            or self.browser.transport not in (None, "cdp")
        ):
            return
        browser = await self._connect_browser()
        directory = await asyncio.to_thread(self.files.download_directory)
        await check_effect_authorization(before_effect)
        self.control._authorize(actor, epoch, target_epoch, False)
        await browser.call(
            "Browser.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": directory},
        )
        self._downloads_ready = True
        await check_effect_authorization(before_effect)
        self.control._authorize(actor, epoch, target_epoch, False)

    async def _dimensions(self, page):
        if self._dialog:
            return self._size
        metrics = await page.call("Page.getLayoutMetrics")
        viewport = metrics.get("cssLayoutViewport", metrics.get("layoutViewport", {}))
        self._size = int(viewport["clientWidth"]), int(viewport["clientHeight"])
        return self._size

    async def state(self, *, before_effect=None):
        # Refresh can discover an externally closed target, so construct the
        # snapshot after refreshing, not before it.
        async def current():
            tabs = await self._refresh()
            await check_effect_authorization(before_effect)
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
            before_effect=before_effect,
        )

    def invalidate_frame(self):
        self._frame_generation += 1
        self._frame = None

    async def drag_view(
        self, viewer: str, controller, epoch, target_epoch, *, before_effect=None
    ):
        async def prepare():
            if viewer not in self._viewers:
                raise ControlError("browser_viewer_not_attached")
            if self._dialog:
                raise ControlError("browser_dialog_open")
            page = await self._connect_page()
            width, height = await self._dimensions(page)
            await check_effect_authorization(before_effect)
            self.control._authorize(controller, epoch, target_epoch, False)
            return PageDrag(page, width, height)

        return await self.control.run(
            controller, epoch, target_epoch, prepare, before_effect=before_effect
        )

    async def frame(
        self,
        viewer: str,
        epoch: int,
        target_epoch: int,
        *,
        during_drag=False,
        before_effect=None,
    ):
        async def capture():
            if viewer not in self._viewers:
                raise ControlError("browser_viewer_not_attached")
            view = await self._view.attach(viewer, before_effect=before_effect)
            # Live page input already owns this connection and the write
            # barrier. Only pixel/layout reads may run alongside that press.
            page = self._page if during_drag else await self._connect_page()
            if page is None or page.disconnected:
                raise ControlError("browser_disconnected")
            await check_effect_authorization(before_effect)
            self.control._authorize("ai", epoch, target_epoch, True)
            if (
                self._frame is None
                or time.monotonic() - self._frame_time >= 0.25
                or self._frame["controlEpoch"] != self.control.epoch
                or self._frame["targetEpoch"] != self.control.target_epoch
            ):
                generation = self._frame_generation
                width, height = await self._dimensions(page)
                await check_effect_authorization(before_effect)
                self.control._authorize("ai", epoch, target_epoch, True)
                data = await view.capture(page, dialog=self._dialog)
                await check_effect_authorization(before_effect)
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
                await check_effect_authorization(before_effect)
                frame = await capture()
                self.control._authorize("ai", epoch, target_epoch, True)
                return frame
            return await self.control.run(
                "ai",
                epoch,
                target_epoch,
                capture,
                observation=True,
                before_effect=before_effect,
            )

    async def _observe(self):
        tabs = await self._refresh()
        # Discovery may legitimately retire an externally closed target. Bind
        # pixels to the version actually selected by this observation, before
        # awaiting layout/accessibility/capture on that exact page.
        observed = self.control.snapshot()
        page = await self._connect_page()
        if self._dialog:
            raise ControlError("browser_dialog_requires_response")
        width, height = await self._dimensions(page)
        tree = await page.call("Accessibility.getFullAXTree")
        # A return always captures current pixels, even with no viewer open.
        view = PageView()
        data = await view.capture(page, dialog=self._dialog)
        self.control._authorize(
            "ai", observed["controlEpoch"], observed["targetEpoch"], True
        )
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
                "controlEpoch": observed["controlEpoch"],
                "targetEpoch": observed["targetEpoch"],
            },
        }

    async def observe(self, epoch: int, target_epoch: int, *, before_effect=None):
        async def current():
            observation = await self._observe()
            await check_effect_authorization(before_effect)
            self.control._authorize(
                "ai", epoch, observation["frame"]["targetEpoch"], True
            )
            return observation

        return await self.control.run(
            "ai",
            epoch,
            target_epoch,
            current,
            observation=True,
            before_effect=before_effect,
        )

    async def diagnostics(
        self, epoch: int, target_epoch: int, *, before_read, authorize_frame
    ):
        """Use to inspect a failed page; returns host-private DOM, AX and full-page PNG.

        Requires current original-browser read and every source-frame's full
        projection/DLP permission. Existing input control and page socket are
        reused in observation mode. A source change withholds the snapshot.

        Args:
            epoch: Original current control epoch.
            target_epoch: Original selected-target epoch.
            before_read: Current original-principal browser diagnostic read assertion.
            authorize_frame: Factory for that principal's full read assertion on
                every source frame, including child-frame pixels and DLP.

        Failure:
            Withhold diagnostics after source or authorization changes. Inspect
            the original operation's status; a snapshot cannot confirm an
            uncertain write and must not cause that write to be replayed.
        """
        from .diagnostics import capture_diagnostics

        return await capture_diagnostics(
            self,
            epoch,
            target_epoch,
            before_read=before_read,
            authorize_frame=authorize_frame,
        )

    async def selection(
        self, controller: str, epoch: int, target_epoch: int, *, before_effect=None
    ):
        """Read only the selected text under the current human input barrier."""

        async def read():
            if self._dialog:
                raise ControlError("browser_dialog_open")
            selected = await PageView().selection(await self._connect_page())
            await check_effect_authorization(before_effect)
            self.control._authorize(controller, epoch, target_epoch, False)
            return selected

        return await self.control.run(
            controller, epoch, target_epoch, read, before_effect=before_effect
        )

    async def take(
        self, controller: str, epoch: int, target_epoch: int, *, before_effect=None
    ):
        if epoch != self.control.epoch or target_epoch != self.control.target_epoch:
            raise ControlError("stale_browser_operation")
        return await self.control.take(controller, before_effect=before_effect)

    async def give_back(
        self, controller: str, epoch: int, target_epoch: int, *, before_effect=None
    ):
        if epoch != self.control.epoch or target_epoch != self.control.target_epoch:
            raise ControlError("stale_browser_operation")
        return await self.control.give_back(
            controller, self._observe, before_effect=before_effect
        )

    async def action(
        self,
        actor: str,
        epoch: int,
        target_epoch: int,
        action: dict,
        *,
        before_effect=None,
    ):
        async def perform():
            self._frame = None
            kind = action["kind"]
            if kind in ("new-tab", "select-tab", "close-tab"):
                browser = await self._connect_browser()
                tabs = await self._refresh()
                await check_effect_authorization(before_effect)
                self.control._authorize(actor, epoch, target_epoch, False)
                if kind == "new-tab":
                    created = await browser.call(
                        "Target.createTarget", {"url": "about:blank"}
                    )
                    await self.browser.update_targets()
                    await self._select(created["targetId"])
                    selected_epoch = self.control.target_epoch
                    page = await self._connect_page()
                    await check_effect_authorization(before_effect)
                    self.control._authorize(actor, epoch, selected_epoch, False)
                    await page.call("Page.bringToFront")
                else:
                    target = action["targetId"]
                    if target not in {tab["id"] for tab in tabs}:
                        raise ControlError("browser_target_closed")
                    if kind == "select-tab":
                        await self._select(target)
                        selected_epoch = self.control.target_epoch
                        page = await self._connect_page()
                        await check_effect_authorization(before_effect)
                        self.control._authorize(actor, epoch, selected_epoch, False)
                        await page.call("Page.bringToFront")
                    else:
                        await browser.call("Target.closeTarget", {"targetId": target})
                        await self._refresh()
                return
            page = await self._connect_page()
            await self._configure_downloads(
                actor, epoch, target_epoch, before_effect=before_effect
            )
            await check_effect_authorization(before_effect)
            self.control._authorize(actor, epoch, target_epoch, False)
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
                    await asyncio.to_thread(
                        self.files.browser_path, file_id, kind="upload"
                    )
                    for file_id in file_ids
                ]
                await check_effect_authorization(before_effect)
                self.control._authorize(actor, epoch, target_epoch, False)
                if self._file_chooser is not chooser:
                    raise ControlError("browser_file_chooser_changed")
                await page.call(
                    "DOM.setFileInputFiles",
                    {"backendNodeId": chooser["node"], "files": paths},
                )
                self._file_chooser = None
            elif kind == "input":
                if self._recording:
                    await self._recording.prepare_input(self.target_id, page)
                width, height = await self._dimensions(page)
                await check_effect_authorization(before_effect)
                self.control._authorize(actor, epoch, target_epoch, False)

                async def input_current():
                    await check_effect_authorization(before_effect)
                    self.control._authorize(actor, epoch, target_epoch, False)
                    if self._page is not page or page.disconnected:
                        raise ControlError("browser_target_closed")

                # Input contains awaited focus/position/press steps. Reuse the
                # original replay guard at each command, on this exact socket.
                # Pure key/button releases still drain after withdrawal.
                if not await PageView().input(
                    _Commands(page, input_current),
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
                    await check_effect_authorization(before_effect)
                    self.control._authorize(actor, epoch, target_epoch, False)
                    await page.call(
                        "Page.navigateToHistoryEntry",
                        {"entryId": history["entries"][index]["id"]},
                    )
            else:
                raise ControlError("invalid_browser_action")

        return await self.control.run(
            actor, epoch, target_epoch, perform, before_effect=before_effect
        )

    async def open_authorized_page(
        self, controller, epoch, target_epoch, url, cookie, *, before_effect=None
    ):
        """Install a host session and open a new owned tab under the human barrier."""
        params = navigation_cookie(url, cookie)

        async def perform():
            if self._dialog:
                raise ControlError("browser_dialog_open")
            previous = self.target_id
            browser = await self._connect_browser()
            await check_effect_authorization(before_effect)
            self.control._authorize(controller, epoch, target_epoch, False)
            created = await browser.call(
                "Target.createTarget", {"url": "about:blank", "background": True}
            )
            page = None
            try:
                await self.browser.update_targets()
                await self._select(created["targetId"])
                selected_epoch = self.control.target_epoch
                page = await self._connect_page()
                await check_effect_authorization(before_effect)
                self.control._authorize(controller, epoch, selected_epoch, False)
                installed = await page.call("Network.setCookie", params)
                if not installed.get("success"):
                    raise ControlError("browser_authorized_page_failed")
                await check_effect_authorization(before_effect)
                self.control._authorize(controller, epoch, selected_epoch, False)
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
                await check_effect_authorization(before_effect)
                self.control._authorize(controller, epoch, selected_epoch, False)
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

        return await self.control.run(
            controller, epoch, target_epoch, perform, before_effect=before_effect
        )

    async def page_operation(
        self, viewer, controller, epoch, target_epoch, operation, *, before_effect
    ):
        """Use for admitted host input; runs its journal and commands under one barrier.

        The callback receives guarded CDP call/send on the current original
        page, not a browser or raw endpoint. Call outside another core.run.
        It must not retain the command handle after this invocation.

        Args:
            viewer: Trusted host viewer identity owning the original input journal.
            controller: Current authenticated human control owner.
            epoch: Original current control epoch.
            target_epoch: Original selected-target epoch.
            operation: Async host callback receiving guarded call/send methods.
                Its return value is returned unchanged after the callback ends.
            before_effect: Mandatory current original input authorization assertion.

        Failure:
            An expired handle or changed input context refuses. Release held
            original inputs with cleanup_input and original journal custody;
            do not reconnect or resend an uncertain input packet.
        """
        if self._host_input is None:
            from .host_input import HostInput

            self._host_input = HostInput(self)
        return await self._host_input.perform(
            viewer,
            controller,
            epoch,
            target_epoch,
            operation,
            before_effect=before_effect,
        )

    async def cleanup_input(self, viewer, controller, operation, *, before_cleanup):
        """Use for held original inputs after withdrawal; releases them on their original socket.

        A current user read grant is not required to release original input;
        before_cleanup must prove its original journal/writer custody instead.
        No frame read, reconnect, new press or cleanup replay is admitted.
        Call outside another core.run, before viewer detach if input is held.

        Args:
            viewer: Original host viewer identity from page_operation.
            controller: Original authenticated human control owner.
            operation: Async host journal callback issuing original key/button
                releases only; succeeds without returning page data.
            before_cleanup: Mandatory current original journal/writer custody
                assertion, distinct from a user read or input grant.

        Failure:
            An uncertain release closes its receipt and puts control in error.
            Retain the original journal and reconcile through its owner; never
            retry cleanup on a replacement page or claim the release succeeded.
        """
        if not callable(before_cleanup) or not callable(operation):
            raise ControlError("browser_authorization_required")
        if self._host_input is not None:
            return await self._host_input.cleanup(
                viewer, controller, operation, before_cleanup=before_cleanup
            )

    async def agent_command(
        self,
        epoch: int,
        target_epoch: int,
        method: str,
        params: dict,
        *,
        frame=None,
        before_effect=None,
    ):
        """Trusted host-only agent command. Arbitrary evaluation counts as a write."""

        async def perform():
            self._frame = None
            page = await self._connect_page()
            await self._configure_downloads(
                "ai", epoch, target_epoch, before_effect=before_effect
            )
            await check_effect_authorization(before_effect)
            self.control._authorize("ai", epoch, target_epoch, False)
            if self._recording:
                await self._recording.prepare_input(self.target_id, page)
                await check_effect_authorization(before_effect)
                self.control._authorize("ai", epoch, target_epoch, False)
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
                await check_effect_authorization(before_effect)
                self.control._authorize("ai", epoch, target_epoch, False)
                return await tab.send(command(), session_id=session, timeout=20)
            except ProtocolException as error:
                mapped = BrowserViewError("operation_failed")
                mapped.details = (
                    error.args[0]
                    if error.args and isinstance(error.args[0], dict)
                    else {"message": str(error)}
                )
                raise mapped from error

        return await self.control.run(
            "ai", epoch, target_epoch, perform, before_effect=before_effect
        )

    async def follow_foreground(
        self, controller: str, epoch: int, target_epoch: int, *, before_effect=None
    ):
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
                    ws = await self.http.ws_connect(
                        tab._connection.websocket_url, max_msg_size=MAX_SIZE
                    )
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

        return await self.control.run(
            controller, epoch, target_epoch, select, before_effect=before_effect
        )

    async def close(self):
        if self._host_input is not None:
            self._host_input.invalidate()
        if self._recording:
            await self._recording.interrupt()
        for viewer in list(self._viewers):
            await self.detach(viewer)
        if self._page:
            await self._page.close()
        if self._browser:
            await self._browser.close()
