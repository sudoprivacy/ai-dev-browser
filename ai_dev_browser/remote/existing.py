"""Explicit host attachment to an already running personal Chrome extension.

The host supplies one shared lease directory for all of its conversations.
Neither discovery nor attachment starts Chrome, installs an extension, changes
its profile, exposes unrelated personal tabs or grants an AI control lease.
"""

import asyncio
import hashlib
import pathlib

from ai_dev_browser.core import _session
from ai_dev_browser.core.browser import browser_connect
from ai_dev_browser.core.connection import connect_extension
from ai_dev_browser.core.ext_bridge import bridge_status, ensure_bridge_running
from ai_dev_browser.core.extension import extension_load_instructions

from .control import ControlError
from .profile_lease import ProfileLease


class ExistingExtension:
    def __init__(self, lease_root):
        self.root = pathlib.Path(lease_root)
        self.lease = None

    @staticmethod
    def identity(status):
        if not status or not status.get("extension_connected"):
            return None
        session, profile = status.get("session_id"), status.get("profile_id")
        if not isinstance(session, str) or not isinstance(profile, str):
            return None
        if not session or not profile or len(session) > 200 or len(profile) > 200:
            return None
        return {"sessionId": "extension-" + session, "profileId": profile}

    async def inspect(self):
        if not await asyncio.to_thread(ensure_bridge_running):
            return {
                "existingExtension": None,
                "setupInstructions": extension_load_instructions(),
            }
        return {
            "existingExtension": self.identity(await bridge_status()),
            "setupInstructions": extension_load_instructions(),
        }

    async def connect(self, expected):
        if self.lease is not None:
            raise ControlError("browser_existing_extension_already_attached")
        status = await bridge_status()
        if self.identity(status) != expected:
            raise ControlError("browser_existing_extension_changed")
        self.root.mkdir(parents=True, exist_ok=True)
        directory = (
            self.root / hashlib.sha256(expected["profileId"].encode()).hexdigest()
        )
        directory.mkdir(exist_ok=True)
        try:
            self.lease = ProfileLease(directory)
        except RuntimeError:
            raise ControlError("browser_existing_profile_in_use") from None
        client = None
        try:
            # Register only the identity the host has just shown and the human
            # explicitly selected. The core connect path then checks this exact
            # run/profile again before exposing any page connection.
            identity = expected["sessionId"]
            try:
                record = _session.read(identity)
            except LookupError:
                record = _session.adopt_launch(status) or {
                    "session_id": identity,
                    "transport": "extension",
                    "owner": "external",
                    "profile_owner": "user",
                }
            if record.get("profile_id") not in (None, expected["profileId"]):
                raise ControlError("browser_existing_extension_changed")
            record.update(
                profile_id=expected["profileId"],
                automation_target_id=status.get("automation_target_id"),
                browser_version=status.get("browser_version"),
            )
            _session.write(record)
            connected = await browser_connect(
                transport="extension", session_id=identity
            )
            if not connected.get("connected"):
                raise ControlError("browser_existing_extension_unavailable")
            if (
                connected.get("session_id") != identity
                or connected.get("profile_id") != expected["profileId"]
            ):
                raise ControlError("browser_existing_extension_changed")
            client = await connect_extension(identity)
            return client, {**expected, "isHeadless": connected.get("headless")}
        except BaseException:
            if client is not None:
                await client.close()
            self.close()
            raise

    def close(self):
        # The application owns its connection and lease, never personal Chrome.
        if self.lease is not None:
            self.lease.close()
            self.lease = None
