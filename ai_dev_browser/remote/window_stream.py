"""Read-only RFB transport; human input stays on the worker's checked API."""

import asyncio
import secrets
import shutil
import socket
import tempfile
from pathlib import Path

import aiohttp
from aiohttp import web

from .control import ControlError
from .vnc import VncView


class WindowStream:
    """Own one optional noVNC adapter for an existing isolated X display.

    The host authenticates every public connection and supplies a validated
    context to the worker. RFB never accepts keyboard, pointer or clipboard
    writes, including from a client that disables its own view-only setting.
    """

    def __init__(self, display):
        self.display = display
        self.directory = None
        self.view = None
        self.password = None
        self.connections = set()

    @staticmethod
    def available():
        return bool(
            shutil.which("x11vnc")
            and shutil.which("websockify")
            and Path("/usr/share/novnc/core/rfb.js").is_file()
        )

    @staticmethod
    def _port():
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    async def start(self):
        pending = None
        try:
            self.directory = tempfile.TemporaryDirectory(prefix="adb-window-view-")
            self.password = secrets.token_hex(4)
            password_file = Path(self.directory.name) / "password"
            password_file.touch(mode=0o600)
            password_file.write_text(self.password, encoding="ascii")
            vnc_port = self._port()
            web_port = self._port()
            while web_port == vnc_port:
                web_port = self._port()
            self.view = VncView(
                display=self.display,
                password_file=password_file,
                vnc_port=vnc_port,
                web_port=web_port,
                view_only=True,
            )
            # A cancelled to_thread call still runs. Wait for startup/cleanup
            # before releasing the display so no orphan can appear afterwards.
            pending = asyncio.create_task(asyncio.to_thread(self.view.start))
            await asyncio.shield(pending)
        except BaseException:
            if pending:
                await asyncio.gather(pending, return_exceptions=True)
            await self.close()
            raise
        return self

    async def close(self):
        if self.connections:
            await asyncio.gather(
                *(socket.close(code=1001) for socket in list(self.connections)),
                return_exceptions=True,
            )
        if self.view:
            await asyncio.to_thread(self.view.close)
        if self.directory:
            self.directory.cleanup()

    async def proxy(self, request, http, validate):
        """Forward binary RFB only while this exact viewer context remains valid.

        Validation has no browser side effects: no target discovery, lease
        release, profile claim or automatic retry. The host must separately
        revalidate the end user's live authentication on its public gateway.
        """
        validate()
        if not self.view or not self.view.running:
            raise ControlError("browser_window_stream_unavailable")
        socket = web.WebSocketResponse(
            heartbeat=10, max_msg_size=1024 * 1024, protocols=("binary",)
        )
        # Connect upstream before accepting. Do not disclose its loopback URL.
        async with http.ws_connect(
            f"http://127.0.0.1:{self.view.web_port}/websockify",
            protocols=("binary",),
            max_msg_size=16 * 1024 * 1024,
        ) as upstream:
            validate()
            await socket.prepare(request)
            self.connections.add(socket)

            async def forward(source, destination):
                async for message in source:
                    validate()
                    if message.type == aiohttp.WSMsgType.BINARY:
                        await destination.send_bytes(message.data)
                    else:
                        break

            async def guard():
                while True:
                    await asyncio.sleep(0.25)
                    validate()

            tasks = [
                asyncio.create_task(forward(socket, upstream)),
                asyncio.create_task(forward(upstream, socket)),
                asyncio.create_task(guard()),
            ]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                # Observe all failures. A stale context closes the stream; it
                # is never a reason to create another browser or replay input.
                await asyncio.gather(*tasks, return_exceptions=True)
                self.connections.discard(socket)
                await socket.close()
        return socket
