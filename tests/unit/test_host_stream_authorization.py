"""A held real loopback stream never releases pixels after current denial."""

import asyncio
from types import SimpleNamespace

import aiohttp
from aiohttp import web

from ai_dev_browser.remote.window_stream import WindowStream


async def serve(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, site._server.sockets[0].getsockname()[1]


async def test_held_binary_stream_reply_is_withdrawn_after_current_denial():
    release = asyncio.Event()
    allowed = True
    validations = []
    sent = []

    async def upstream(request):
        socket = web.WebSocketResponse(protocols=("binary",))
        await socket.prepare(request)
        await release.wait()
        sent.append("one upstream payload")
        await socket.send_bytes(b"private fixture pixels")
        await socket.receive()
        await socket.close()
        return socket

    async def current():
        if not allowed:
            raise PermissionError("private original grant")

    def validate():
        validations.append(True)

    source = web.Application()
    source.router.add_get("/websockify", upstream)
    source_runner, source_port = await serve(source)
    stream = WindowStream(None)
    stream.view = SimpleNamespace(running=True, web_port=source_port)
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as http:

            async def proxy(request):
                return await stream.proxy(
                    request, http, validate, before_effect=current
                )

            target = web.Application()
            target.router.add_get("/view", proxy)
            target_runner, target_port = await serve(target)
            try:
                async with http.ws_connect(
                    f"http://127.0.0.1:{target_port}/view", protocols=("binary",)
                ) as client:
                    allowed = False
                    release.set()
                    message = await client.receive(timeout=2)
                    assert message.type in {
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.CLOSED,
                    }
                    assert message.data != b"private fixture pixels"
                assert sent == ["one upstream payload"]
                assert len(validations) >= 4
                assert stream.connections == set()
            finally:
                release.set()
                await target_runner.cleanup()
    finally:
        release.set()
        await source_runner.cleanup()
