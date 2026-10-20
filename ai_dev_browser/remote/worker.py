"""Authenticated browser worker shared by local and cloud application hosts.

The application host authenticates human callers. AI has a separate credential and can never
take/return human control. No raw CDP, extension or VNC port is published.
"""

import asyncio
import hashlib
import hmac
import json
import os
import pathlib
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import unquote

import aiohttp
from aiohttp import web

from ai_dev_browser.core.browser import browser_connect, browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, connect_extension
from ai_dev_browser.remote.cdp import BrowserViewError
from ai_dev_browser.remote.control import BrowserControl, ControlError, SharedViewer
from ai_dev_browser.remote.files import BrowserFiles
from ai_dev_browser.remote.provision import (
    configure_managed_extension_file_access,
    prepare_managed_extension_profile,
)
from ai_dev_browser.remote.session import BrowserSession
from ai_dev_browser.remote.window import WindowView, XDisplay

from .profile_lease import ProfileLease
from .existing import ExistingExtension


class Worker:
    def __init__(
        self,
        root,
        host_token,
        ai_token,
        *,
        chrome_path=None,
        display_mode="x11",
        extension_directory=None,
        chrome_args=(),
        existing_extension_root=None,
    ):
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.host_token, self.ai_token = host_token, ai_token
        if not host_token or not ai_token or host_token == ai_token:
            raise ValueError("Distinct host and AI credentials required")
        self.profile_lease = ProfileLease(self.root)
        self.files = BrowserFiles(self.root / "files")
        self.file_permission_prepared = False
        self.chrome_path = chrome_path
        if display_mode not in ("x11", "native"):
            raise ValueError("An explicit x11 or native display mode is required")
        self.display_mode = display_mode
        self.extension_directory = (
            pathlib.Path(extension_directory) if extension_directory else None
        )
        self.chrome_args = list(chrome_args)
        self.existing_extension = (
            ExistingExtension(existing_extension_root)
            if existing_extension_root
            else None
        )
        self.personal_reference = None
        self.binding = None
        self.browser = None
        self.pending_launch = None
        self.session = None
        self.http = None
        self.display = None
        self.lifecycle = asyncio.Lock()
        self.lifecycle_changes = 0
        self.viewers = {}
        self.window_viewers = set()
        self.window_frame = None
        self.window_frame_time = 0
        self.window_view = SharedViewer(self.open_window, self.close_window)
        self.control = BrowserControl()
        self.handoff = None
        self.journal = self.root / "control.json"
        if self.journal.exists():
            saved = json.loads(self.journal.read_text())
            self.binding = saved["binding"]
            self.handoff = saved.get("handoff")
            self.personal_reference = saved.get("personalExtension")
            self.control.epoch = saved["controlEpoch"] + 1
            self.control.target_epoch = saved["targetEpoch"] + 1
            # Recovery never resumes old AI plans. A human explicitly restarts
            # the stopped browser and returns it after a fresh observation.
            self.control.controller = saved.get("controller")
            self.control.state = "error"
            self.control.error = "browser_restart_requires_observation"

    def save(self, *, controller=None, state=None):
        if self.binding is None:
            return
        value = {
            "binding": self.binding,
            "handoff": self.handoff,
            "personalExtension": self.personal_reference,
            **self.control.snapshot(),
        }
        if controller is not None:
            value["controller"] = controller
        if state is not None:
            value["state"] = state
        temporary = self.root / (".control-" + secrets.token_hex(8))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump(value, file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, self.journal)

    @staticmethod
    def validate_binding(binding):
        if not isinstance(binding, dict) or set(binding) != {
            "orgId",
            "userId",
            "sessionId",
        }:
            raise ControlError("invalid_browser_binding")
        if not all(
            isinstance(value, str) and 0 < len(value) <= 256
            for value in binding.values()
        ):
            raise ControlError("invalid_browser_binding")

    def bind(self, binding):
        self.validate_binding(binding)
        if self.binding is None:
            self.binding = binding.copy()
            self.save()
        elif self.binding != binding:
            raise ControlError("browser_profile_in_use")

    def profile_id(self):
        if self.personal_reference:
            return "personal-" + self.personal_reference["profileId"]
        return hashlib.sha256(
            json.dumps(
                {key: self.binding[key] for key in ("orgId", "userId")}, sort_keys=True
            ).encode()
        ).hexdigest()[:16]

    async def rebind(self, binding, previous_session, controller):
        """Move a profile only after the host verifies the old session ended."""
        self.validate_binding(binding)
        if self.binding is None or self.binding == binding:
            self.bind(binding)
            return
        if self.binding["sessionId"] != previous_session or any(
            self.binding[key] != binding.get(key) for key in ("orgId", "userId")
        ):
            raise ControlError("browser_profile_in_use")
        async with self.changing_lifecycle():
            was_ai = self.control.state == "ai"
            if self.session and was_ai:
                self.save(controller=controller, state="pausing")
                await self.session.take(
                    controller, self.control.epoch, self.control.target_epoch
                )
            self.binding = binding.copy()
            self.handoff = None
            self.control.target_epoch += 1
            self.save()
            # A human lease survives conversation changes. An AI lease can
            # move only after draining old commands and observing this page.
            if self.session and was_ai:
                await self.session.give_back(
                    controller, self.control.epoch, self.control.target_epoch
                )
                self.save()

    @asynccontextmanager
    async def changing_lifecycle(self):
        self.lifecycle_changes += 1
        try:
            async with self.lifecycle:
                yield
        finally:
            self.lifecycle_changes -= 1

    async def state(self, controller=None):
        if self.lifecycle_changes:
            # Closing/replacing a browser invalidates its driver before all
            # resources have drained. Status stays responsive and never queries
            # that retiring connection or presents it as ready for input.
            live = {
                **self.control.snapshot(),
                "state": "pausing",
                "activeTargetId": None,
                "tabs": [],
            }
            return self._state_reply(live, controller, is_transitioning=True)
        async with self.lifecycle:
            return await self._current_state(controller)

    async def _current_state(self, controller):
        live = (
            await self.session.state()
            if self.session
            else {**self.control.snapshot(), "activeTargetId": None, "tabs": []}
        )
        return self._state_reply(live, controller)

    def _state_reply(self, live, controller, *, is_transitioning=False):
        return {
            "browserSessionId": self.browser["session_id"]
            if self.browser
            else "stopped-" + self.profile_id(),
            "profileId": self.profile_id(),
            "state": live["state"] if self.session or is_transitioning else "stopped",
            "controlEpoch": live["controlEpoch"],
            "targetEpoch": live["targetEpoch"],
            "isController": bool(controller and live["controller"] == controller),
            "isHumanControlHeld": live["controller"] is not None,
            "isHeadless": self.browser.get("headless")
            if self.browser
            else self.personal_reference.get("isHeadless")
            if self.personal_reference
            else True,
            "transport": self.browser.get("transport", "extension")
            if self.browser
            else "extension",
            "capabilities": {
                "dragInput": True,
                "clipboardText": True,
                "selectionRead": True,
                "lifecycle": self.personal_reference is None,
                "fileTransfer": self.personal_reference is None,
                "existingExtension": self.existing_extension is not None,
                "pageView": bool(self.session and not is_transitioning),
                "windowView": bool(
                    self.session and self.display and not is_transitioning
                ),
                "persistentProfile": True,
            },
            "activeTargetId": live["activeTargetId"],
            "tabs": live["tabs"],
            "error": live["error"],
            "personalExtension": self.personal_reference,
            "handoff": self.handoff,
            "dialog": live.get("dialog"),
            "fileChooser": live.get("fileChooser"),
            "downloads": self.files.collect_downloads(),
        }

    async def open_window(self):
        if not self.display or not self.browser or self.browser["headless"]:
            raise ControlError("browser_window_view_unavailable")
        return WindowView(display=self.display.display)

    async def close_window(self, view):
        await view.close()
        self.window_frame = None

    @staticmethod
    def surface(action):
        surface = action.get("surface", "page")
        if surface not in ("page", "window"):
            raise ControlError("invalid_browser_surface")
        return surface

    async def capture_window(self, viewer, epoch, target_epoch):
        async def capture():
            if viewer not in self.window_viewers:
                raise ControlError("browser_viewer_not_attached")
            view = await self.window_view.attach(viewer)
            key = (self.control.epoch, self.control.target_epoch)
            if (
                self.window_frame is None
                or self.window_frame["controlEpoch"] != key[0]
                or self.window_frame["targetEpoch"] != key[1]
                or time.monotonic() - self.window_frame_time > 0.25
            ):
                self.window_frame = {
                    **await view.capture(),
                    "controlEpoch": key[0],
                    "targetEpoch": key[1],
                    "surface": "window",
                }
                self.window_frame_time = time.monotonic()
            return self.window_frame

        return await self.control.run(
            "ai", epoch, target_epoch, capture, observation=True
        )

    async def input_window(self, controller, epoch, target_epoch, event):
        async def perform():
            await self.session._connect_page()
            if not self.window_viewers:
                raise ControlError("browser_viewer_not_attached")
            view = await self.window_view.attach(next(iter(self.window_viewers)))
            if not await view.input(event):
                raise ControlError("invalid_browser_input")
            self.window_frame = None

        await self.control.run(controller, epoch, target_epoch, perform)
        await self.session.follow_foreground(controller, epoch, target_epoch)

    async def start(self, action, actor):
        async with self.changing_lifecycle():
            await self._start_browser(action, actor)

    async def _start_browser(self, action, actor):
        if self.personal_reference is not None:
            raise ControlError("browser_existing_extension_requires_disconnect")
        is_headless, transport = (
            action.get("isHeadless"),
            action.get("transport", "extension"),
        )
        if not isinstance(is_headless, bool) or transport not in (
            "cdp",
            "extension",
        ):
            raise ControlError("explicit_browser_launch_mode_required")
        if actor == "ai" and self.control.state != "ai":
            raise ControlError(
                "browser_control_held_by_user"
                if self.control.controller is not None
                else self.control.error or "browser_control_held_by_user"
            )
        if actor != "ai" and self.control.controller not in (None, actor):
            raise ControlError("browser_control_not_owned")
        if self.session:
            if (
                self.browser["headless"] != is_headless
                or self.browser["transport"] != transport
            ):
                raise ControlError("browser_restart_required")
            return
        if not is_headless and self.display_mode == "x11":
            if os.name == "nt":
                raise ControlError("managed_window_view_requires_linux")
            if self.display is None:
                self.display = XDisplay()
                await self.display.start()
        profile = self.root / "chrome"
        profile.mkdir(exist_ok=True)
        if not self.pending_launch:
            try:
                self.profile_lease.prepare(profile)
            except RuntimeError as error:
                raise ControlError(str(error)) from None
        arguments = {
            "headless": is_headless,
            "transport": transport,
            "chrome_path": self.chrome_path,
            "silent_stderr": True,
            "stealth": False,
            "extra_args": self.chrome_args.copy(),
        }
        if self.display is not None:
            arguments["display"] = self.display.display
        if not is_headless:
            arguments["extra_args"] += [
                "--window-size=1280,900",
                "--start-maximized",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ]
        if transport == "extension":
            arguments["user_data_dir"] = str(profile)
            identity = (
                self.extension_directory / "identity.json"
                if self.extension_directory
                else None
            )
            if identity is not None and identity.exists():
                installed_identity = json.loads(identity.read_text())
                try:
                    await prepare_managed_extension_profile(
                        str(profile),
                        extension_id=installed_identity["id"],
                        minimum_version=installed_identity["version"],
                        chrome_path=self.chrome_path,
                        extra_args=arguments["extra_args"],
                    )
                    if not self.file_permission_prepared:
                        await configure_managed_extension_file_access(
                            str(profile),
                            extension_id=installed_identity["id"],
                            enabled=True,
                            chrome_path=self.chrome_path,
                            extra_args=arguments["extra_args"],
                        )
                        self.file_permission_prepared = True
                except ControlError as error:
                    diagnostic = self.root / "launch-failure.json"
                    diagnostic.write_text(
                        json.dumps(error.details or {"error_code": error.code})
                    )
                    diagnostic.chmod(0o600)
                    raise
        else:
            arguments["profile"] = str(profile)
            # Both transports own the same Chrome profile. CDP must retain the
            # managed extension and its policy updates for a later mode change.
            arguments["override_default_args"] = {
                "--remote-allow-origins": None,
                "--disable-extensions": None,
                "--disable-background-networking": None,
            }
        if self.pending_launch:
            # Explicitly reconnect an owned late launch. Never start a
            # second Chrome or replay an uncertain browser input.
            connected = await browser_connect(transport=transport)
            if (
                not connected.get("connected")
                or connected.get("owner") != "adb"
                or connected.get("pid") != self.pending_launch.get("pid")
                or pathlib.Path(connected.get("user_data_dir", "")).resolve()
                != profile.resolve()
                or bool(connected.get("headless")) != is_headless
            ):
                raise ControlError("managed_browser_reconnect_required")
            launched = connected
        else:
            self.files.configure_managed_profile(profile)
            launched = await asyncio.to_thread(browser_start, **arguments)
        if "error" in launched:
            diagnostic = self.root / "launch-failure.json"
            diagnostic.write_text(
                json.dumps(
                    {
                        key: launched.get(key)
                        for key in (
                            "error",
                            "error_code",
                            "pid",
                            "launch_token",
                            "started",
                        )
                    }
                )
            )
            diagnostic.chmod(0o600)
            if (
                launched.get("started")
                and launched.get("launch_token")
                and launched.get("pid")
            ):
                self.pending_launch = launched
            if self.display:
                await self.display.close()
                self.display = None
            raise ControlError(
                "browser_extension_not_ready"
                if transport == "extension"
                else "browser_start_failed"
            )
        self.browser = {**launched, "headless": is_headless, "transport": transport}
        self.pending_launch = None
        client = await (
            connect_extension(launched["session_id"])
            if transport == "extension"
            else connect_browser(session_id=launched["session_id"])
        )
        self.session = BrowserSession(
            client, self.http, control=self.control, files=self.files
        )
        if not is_headless:
            page = await self.session._connect_page()
            await page.call("Page.bringToFront")
        if self.control.state == "error" and actor != "ai":
            self.control.state = "human"
            self.control.controller = actor
        self.control.epoch += 1
        self.save()

    async def _stop_browser(self):
        for viewer in list(self.window_viewers):
            await self.window_view.detach(viewer)
        if self.session:
            await self.session.close()
            await self.session.browser.close()
        self.session = None
        self.viewers.clear()
        self.window_viewers.clear()
        self.window_frame = None
        record = self.browser or self.pending_launch
        if record and not record.get("external_attachment"):
            session_id = record.get("session_id")
            if not session_id:
                raise ControlError("managed_browser_reconnect_required")
            result = await asyncio.to_thread(browser_stop, session_id=session_id)
            if result.get("stopped") is not True:
                self.pending_launch = record
                raise ControlError("browser_stop_uncertain")
        self.browser = None
        self.pending_launch = None
        if self.existing_extension:
            self.existing_extension.close()
        if self.display:
            await self.display.close()
            self.display = None

    async def lifecycle_action(self, actor, action):
        if self.personal_reference is not None:
            raise ControlError("browser_existing_extension_requires_disconnect")
        kind = action.get("kind")
        if kind == "restart":
            if action.get("acknowledgeStateLoss") is not True:
                raise ControlError("browser_restart_acknowledgement_required")
            if type(action.get("isHeadless")) is not bool or action.get(
                "transport"
            ) not in ("extension", "cdp"):
                raise ControlError("explicit_browser_launch_mode_required")
        epoch, target_epoch = self.epochs(action)
        async with self.changing_lifecycle():

            async def perform():
                # Fence queued coordinates before closing any browser resource.
                # Recovery never resumes plans from before this transition.
                self.control.epoch += 1
                self.control.target_epoch += 1
                self.handoff = None
                self.save(state="error")
                try:
                    await self._stop_browser()
                    if kind == "restart":
                        await self._start_browser(action, actor)
                except BaseException:
                    if self.control.state == "ai":
                        self.control.state = "error"
                    self.control.error = "browser_restart_requires_observation"
                    self.save()
                    raise
                self.save()

            await self.control.run(actor, epoch, target_epoch, perform)
        reply = {"session": await self.state(actor if actor != "ai" else None)}
        if kind == "restart" and self.session:
            reply["observation"] = await self.session.observe(
                self.control.epoch, self.control.target_epoch
            )
        return reply

    async def give_back(self, controller, action):
        epoch, target_epoch = self.epochs(action)
        note = action.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > 2000):
            raise ControlError("invalid_browser_handoff_note")
        if self.session:
            _, observation = await self.session.give_back(
                controller, epoch, target_epoch
            )
        else:
            if self.browser or self.pending_launch or self.display:
                raise ControlError("managed_browser_reconnect_required")
            if epoch != self.control.epoch or target_epoch != self.control.target_epoch:
                raise ControlError("stale_browser_operation")

            async def observe_stopped():
                return {
                    "stopped": True,
                    "profileId": self.profile_id(),
                    "activeTargetId": None,
                    "tabs": [],
                }

            _, observation = await self.control.give_back(controller, observe_stopped)
        self.handoff = {
            "controlEpoch": self.control.epoch,
            "note": note or "",
            "returnedAt": time.time(),
        }
        self.save()
        return {"session": await self.state(controller), "observation": observation}

    @staticmethod
    def epochs(action):
        values = action.get("controlEpoch"), action.get("targetEpoch")
        if any(type(value) is not int or value < 0 for value in values):
            raise ControlError("invalid_browser_epoch")
        return values

    async def invoke(self, controller, action):
        kind = action.get("kind")
        extra = {}
        if kind == "state":
            pass
        elif kind == "inspect-existing-extension":
            if self.existing_extension is None:
                raise ControlError("browser_existing_extension_not_supported")
            extra.update(await self.existing_extension.inspect())
        elif kind == "connect-existing-extension":
            if self.existing_extension is None:
                raise ControlError("browser_existing_extension_not_supported")
            expected = {
                "sessionId": action.get("sessionId"),
                "profileId": action.get("profileId"),
            }
            if any(
                not isinstance(value, str) or not value or len(value) > 220
                for value in expected.values()
            ):
                raise ControlError("invalid_browser_request")
            async with self.changing_lifecycle():
                if self.session or self.browser or self.pending_launch:
                    raise ControlError("browser_restart_required")
                if self.personal_reference is not None and any(
                    self.personal_reference[key] != value
                    for key, value in expected.items()
                ):
                    raise ControlError("browser_existing_extension_changed")
                await self.control.take(controller)
                self.control.epoch += 1
                self.control.target_epoch += 1
                self.save(state="pausing")
                client, reference = await self.existing_extension.connect(expected)
                self.personal_reference = reference
                self.browser = {
                    "session_id": reference["sessionId"],
                    "headless": reference["isHeadless"],
                    "transport": "extension",
                    "external_attachment": True,
                }
                self.session = BrowserSession(client, self.http, control=self.control)
                self.save()
                page = await self.session._connect_page()
                await page.call("Page.bringToFront")
        elif kind == "disconnect-existing-extension":
            if self.existing_extension is None or self.personal_reference is None:
                raise ControlError("browser_existing_extension_not_supported")
            epoch, target_epoch = self.epochs(action)
            async with self.changing_lifecycle():
                if (
                    epoch != self.control.epoch
                    or target_epoch != self.control.target_epoch
                ):
                    raise ControlError("stale_browser_operation")
                if self.session is None and self.control.state == "error":
                    # A crashed worker can retain the personal identity with
                    # no live driver or human controller. The authenticated
                    # host may explicitly take its stopped lease to disconnect
                    # that reference; it never starts or switches Chrome.
                    await self.control.take(controller)
                    epoch = self.control.epoch
                    self.save()

                async def disconnect():
                    self.control.epoch += 1
                    self.control.target_epoch += 1
                    await self._stop_browser()
                    self.personal_reference = None
                    self.save()

                await self.control.run(controller, epoch, target_epoch, disconnect)
        elif kind == "start":
            await self.start(action, controller)
        elif kind in ("stop", "restart"):
            return await self.lifecycle_action(controller, action)
        elif kind == "return":
            return await self.give_back(controller, action)
        elif kind in ("attach", "detach"):
            viewer = action.get("viewerId")
            if not isinstance(viewer, str) or len(viewer) > 128:
                raise ControlError("invalid_browser_viewer")
            owned = controller + ":" + viewer
            if self.session:
                if kind == "attach":
                    self.viewers[owned] = time.monotonic()
                    if self.surface(action) == "window":
                        self.window_viewers.add(owned)
                        await self.session.detach(owned)
                        await self.window_view.attach(owned)
                    else:
                        self.window_viewers.discard(owned)
                        await self.window_view.detach(owned)
                        await self.session.attach(owned)
                else:
                    self.viewers.pop(owned, None)
                    self.window_viewers.discard(owned)
                    await self.window_view.detach(owned)
                    await self.session.detach(owned)
        else:
            if not self.session:
                raise ControlError("browser_not_started")
            epoch, target_epoch = self.epochs(action)
            if kind == "take":
                # Persist the intent before allowing the async drain to run.
                # A crash during takeover therefore cannot restore AI control.
                if (
                    epoch != self.control.epoch
                    or target_epoch != self.control.target_epoch
                ):
                    raise ControlError("stale_browser_operation")
                if self.control.controller not in (None, controller):
                    raise ControlError("browser_control_not_owned")
                if self.control.state not in ("ai", "error", "human"):
                    raise ControlError("browser_control_transfer_in_progress")
                self.save(controller=controller, state="pausing")
                await self.session.take(controller, epoch, target_epoch)
            elif kind == "frame":
                owned = controller + ":" + str(action.get("viewerId"))
                if owned not in self.viewers:
                    raise ControlError("browser_viewer_not_attached")
                self.viewers[owned] = time.monotonic()
                if self.surface(action) == "window":
                    extra["frame"] = await self.capture_window(
                        owned, epoch, target_epoch
                    )
                else:
                    extra["frame"] = {
                        **await self.session.frame(owned, epoch, target_epoch),
                        "surface": "page",
                    }
            elif (
                kind == "input"
                and isinstance(action.get("input"), dict)
                and action["input"].get("kind") == "copy-selection"
            ):
                extra["selection"] = await self.session.selection(
                    controller, epoch, target_epoch
                )
            elif kind == "input" and self.surface(action) == "window":
                await self.input_window(
                    controller, epoch, target_epoch, action["input"]
                )
            else:
                await self.session.action(controller, epoch, target_epoch, action)
            self.save()
        return {"session": await self.state(controller), **extra}

    async def agent(self, action):
        kind = action.get("kind")
        if kind in ("stop", "restart"):
            return await self.lifecycle_action("ai", action)
        if kind == "start":
            await self.start(action, "ai")
            return {"session": await self.state()}
        if kind == "state":
            return {"session": await self.state()}
        if not self.session:
            raise ControlError("browser_not_started")
        epoch, target_epoch = self.epochs(action)
        if kind == "observe":
            observation = await self.session.observe(epoch, target_epoch)
            current = await self.state()
            if (
                current["controlEpoch"] != epoch
                or current["targetEpoch"] != target_epoch
            ):
                raise ControlError("stale_browser_operation")
            return {"session": current, "observation": observation}
        if kind == "command":
            method, params = action.get("method"), action.get("params", {})
            # Page commands stay on the selected target. Browser/Target/remote
            # endpoint commands are owned by the session lifecycle instead.
            if (
                not isinstance(method, str)
                or method
                not in {
                    "Page.getLayoutMetrics",
                    "Page.captureScreenshot",
                    "Page.reload",
                    "Page.getNavigationHistory",
                    "Page.navigateToHistoryEntry",
                    "Runtime.evaluate",
                    "Runtime.callFunctionOn",
                    "Runtime.getProperties",
                    "DOM.getDocument",
                    "DOM.getFlattenedDocument",
                    "DOM.describeNode",
                    "DOM.querySelector",
                    "DOM.querySelectorAll",
                    "DOM.getBoxModel",
                    "DOM.getContentQuads",
                    "DOM.getAttributes",
                    "DOM.getOuterHTML",
                    "DOM.focus",
                    "DOM.scrollIntoViewIfNeeded",
                    "Input.dispatchMouseEvent",
                    "Input.dispatchKeyEvent",
                    "Input.insertText",
                    "Accessibility.getFullAXTree",
                    "Accessibility.getPartialAXTree",
                }
                or not isinstance(params, dict)
            ):
                raise ControlError("invalid_browser_command")
            result = await self.session.agent_command(
                epoch, target_epoch, method, params
            )
        elif kind in {
            "input",
            "navigate",
            "back",
            "forward",
            "reload",
            "new-tab",
            "select-tab",
            "close-tab",
            "upload-files",
        }:
            result = await self.session.action("ai", epoch, target_epoch, action)
        else:
            raise ControlError("invalid_agent_browser_action")
        self.save()
        return {"session": await self.state(), "result": result}

    async def reap_viewers(self):
        while True:
            await asyncio.sleep(5)
            if self.session:
                for viewer, heartbeat in list(self.viewers.items()):
                    if time.monotonic() - heartbeat > 20:
                        self.viewers.pop(viewer, None)
                        self.window_viewers.discard(viewer)
                        await self.window_view.detach(viewer)
                        await self.session.detach(viewer)

    async def close(self):
        await self._stop_browser()
        self.profile_lease.close()

    async def receive_file(self, controller, epoch, target_epoch, name, data):
        async def receive():
            return self.files.receive(name, data)

        return await self.control.run(controller, epoch, target_epoch, receive)


def application(worker):
    reaper_key = web.AppKey("viewer_reaper", asyncio.Task)

    @web.middleware
    async def errors(request, handler):
        try:
            return await handler(request)
        except (ControlError, BrowserViewError) as error:
            return web.json_response({"error": error.code}, status=409)
        except (aiohttp.ClientError, ConnectionError, TimeoutError):
            return web.json_response({"error": "browser_disconnected"}, status=503)
        except (KeyError, TypeError, ValueError):
            return web.json_response({"error": "invalid_browser_request"}, status=400)

    def authorize(request, token):
        if not hmac.compare_digest(
            request.headers.get("Authorization", ""), "Bearer " + token
        ):
            raise web.HTTPForbidden()

    async def invoke(request):
        authorize(request, worker.host_token)
        body = await request.json()
        controller = body["controller"]
        if not isinstance(controller, str) or not controller.startswith("user-"):
            raise ControlError("invalid_browser_controller")
        if body["action"].get("kind") == "bind-session":
            await worker.rebind(
                body["binding"], body["action"].get("previousSessionId"), controller
            )
            return web.json_response({"session": await worker.state(controller)})
        worker.bind(body["binding"])
        return web.json_response(await worker.invoke(controller, body["action"]))

    async def binding(request):
        authorize(request, worker.host_token)
        return web.json_response({"binding": worker.binding})

    def file_context(request):
        authorize(request, worker.host_token)
        header = request.headers.get("X-ADB-Browser-Context") or request.headers.get(
            "X-Moss-Browser-Context", ""
        )
        if len(header) > 4096:
            raise ControlError("invalid_browser_request")
        context = json.loads(unquote(header))
        controller = context["controller"]
        if not isinstance(controller, str) or not controller.startswith("user-"):
            raise ControlError("invalid_browser_controller")
        worker.bind(context["binding"])
        return context

    async def receive_file(request):
        context = file_context(request)
        epoch, target_epoch = worker.epochs(context)
        name = unquote(
            request.headers.get("X-ADB-Browser-File-Name")
            or request.headers.get("X-Moss-Browser-File-Name", "")
        )
        payload = bytearray()
        async for chunk in request.content.iter_chunked(64 * 1024):
            payload.extend(chunk)
            if len(payload) > worker.files.max_file_bytes:
                raise ControlError("browser_files_too_large")
        uploaded = await worker.receive_file(
            context["controller"], epoch, target_epoch, name, bytes(payload)
        )
        return web.json_response({"file": uploaded})

    async def read_file(request):
        context = file_context(request)
        if not isinstance(context.get("fileId"), str):
            raise ControlError("browser_file_not_found")
        path = worker.files.path(context["fileId"], kind="download")
        data = path.read_bytes()
        metadata = worker.files.metadata(context["fileId"])
        if (
            len(data) != metadata["bytes"]
            or hashlib.sha256(data).hexdigest() != metadata["sha256"]
        ):
            raise ControlError("browser_file_changed")
        return web.Response(body=data, content_type="application/octet-stream")

    async def agent(request):
        authorize(request, worker.ai_token)
        if worker.binding is None:
            raise ControlError("browser_binding_required")
        return web.json_response(await worker.agent(await request.json()))

    tools = json.loads(
        pathlib.Path(__file__).with_name("mcp-tools.json").read_text(encoding="utf-8")
    )

    async def mcp(request):
        authorize(request, worker.ai_token)
        expected_session = request.headers.get(
            "X-ADB-Browser-Session"
        ) or request.headers.get("X-Moss-Browser-Session")
        if expected_session is not None and (
            worker.binding is None or expected_session != worker.binding["sessionId"]
        ):
            raise ControlError("browser_session_changed")
        message = await request.json()
        rpc_id, method = message.get("id"), message.get("method")
        if rpc_id is None:
            return web.Response(status=202)
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ai-dev-browser", "version": "0.1.0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": tools}
        elif method == "tools/call":
            if worker.binding is None:
                raise ControlError("browser_binding_required")
            params = message.get("params", {})
            name, arguments = params.get("name"), params.get("arguments", {})
            try:
                if name == "browser_launch":
                    value = await worker.agent({**arguments, "kind": "start"})
                elif name == "browser_stop":
                    value = await worker.agent({**arguments, "kind": "stop"})
                elif name == "browser_restart":
                    value = await worker.agent({**arguments, "kind": "restart"})
                elif name == "browser_observe":
                    current = await worker.state()
                    value = (
                        await worker.agent(
                            {
                                "kind": "observe",
                                "controlEpoch": current["controlEpoch"],
                                "targetEpoch": current["targetEpoch"],
                            }
                        )
                        if worker.session
                        else {"session": current}
                    )
                elif name == "browser_action" and arguments.get("kind") in {
                    "navigate",
                    "input",
                    "reload",
                    "back",
                    "forward",
                    "new-tab",
                    "select-tab",
                    "close-tab",
                    "upload-files",
                    "command",
                }:
                    if arguments.get("kind") == "command":
                        raw_params = arguments.get("paramsJson", "{}")
                        if not isinstance(raw_params, str) or len(raw_params) > 262144:
                            raise ControlError("invalid_browser_command")
                        try:
                            command_params = json.loads(raw_params)
                        except ValueError:
                            raise ControlError("invalid_browser_command") from None
                        arguments = {**arguments, "params": command_params}
                    value = await worker.agent(arguments)
                else:
                    raise ControlError("invalid_agent_browser_action")
                content = [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                key: val
                                for key, val in value.items()
                                if key != "observation"
                            }
                        ),
                    }
                ]
                if value.get("observation"):
                    observation = value["observation"].copy()
                    frame = observation.pop("frame")
                    content.append({"type": "text", "text": json.dumps(observation)})
                    if frame["data"]:
                        content.append(
                            {
                                "type": "image",
                                "data": frame["data"],
                                "mimeType": "image/jpeg",
                            }
                        )
                result = {"content": content}
            except (ControlError, BrowserViewError) as error:
                result = {
                    "isError": True,
                    "content": [{"type": "text", "text": error.code}],
                }
        else:
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": -32601, "message": "Method not found"},
                }
            )
        return web.json_response({"jsonrpc": "2.0", "id": rpc_id, "result": result})

    async def start(app):
        worker.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25))
        app[reaper_key] = asyncio.create_task(worker.reap_viewers())

    async def stop(app):
        app[reaper_key].cancel()
        await asyncio.gather(app[reaper_key], return_exceptions=True)
        await worker.close()
        await worker.http.close()

    app = web.Application(middlewares=[errors], client_max_size=16 * 1024 * 1024)
    app.add_routes(
        [
            web.get("/binding", binding),
            web.post("/invoke", invoke),
            web.post("/agent", agent),
            web.post("/mcp", mcp),
            web.post("/files/receive", receive_file),
            web.post("/files/read", read_file),
        ]
    )
    extension = worker.extension_directory
    if extension is not None and extension.exists():
        app.router.add_static("/extension/", extension)

        async def update(request):
            return web.FileResponse(extension / "update.xml")

        async def package(request):
            return web.FileResponse(extension / "bridge.crx")

        app.add_routes(
            [web.get("/update.xml", update), web.get("/bridge.crx", package)]
        )
    app.on_startup.append(start)
    app.on_cleanup.append(stop)
    return app


if __name__ == "__main__":
    # Chrome must not inherit the worker's privileged host credential.
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-root", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--display", choices=("native", "x11"), default="native")
    parser.add_argument("--extension-directory")
    parser.add_argument("--chrome-arg", action="append", default=[])
    parser.add_argument(
        "--existing-extension-root",
        help="Trusted host lease directory shared by all personal-Chrome conversations; omitted disables attachment",
    )
    options = parser.parse_args()
    host_token = os.environ.pop("AI_DEV_BROWSER_WORKER_HOST_TOKEN")
    ai_token = os.environ.pop("AI_DEV_BROWSER_WORKER_AI_TOKEN")
    worker = Worker(
        options.profile_root,
        host_token,
        ai_token,
        chrome_path=os.environ.get("AI_DEV_BROWSER_CHROME"),
        display_mode=options.display,
        extension_directory=options.extension_directory,
        chrome_args=options.chrome_arg,
        existing_extension_root=options.existing_extension_root,
    )
    web.run_app(
        application(worker),
        host=options.host,
        port=options.port,
        access_log=None,
    )
