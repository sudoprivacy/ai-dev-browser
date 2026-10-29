"""The /binding read must expose whether the owned browser is currently running."""

import secrets
from types import SimpleNamespace

import aiohttp
from aiohttp import web

from ai_dev_browser.remote.worker import Worker, application


async def test_binding_reports_browser_running(tmp_path):
    host_token, ai_token = secrets.token_hex(32), secrets.token_hex(32)
    worker = Worker(tmp_path, host_token, ai_token, display_mode="native")
    worker.bind({"orgId": "fixture", "userId": "owner", "sessionId": "binding-read"})
    runner = web.AppRunner(application(worker))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    origin = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    headers = {"Authorization": "Bearer " + host_token}

    async def read_binding():
        async with aiohttp.ClientSession() as http:
            async with http.get(origin + "/binding", headers=headers) as response:
                assert response.status == 200, await response.text()
                return await response.json()

    async def close_browser():
        pass

    class RunningSession:
        browser = SimpleNamespace(close=close_browser)

        async def close(self):
            pass

    try:
        idle = await read_binding()
        assert idle["binding"] == {
            "orgId": "fixture",
            "userId": "owner",
            "sessionId": "binding-read",
        }
        assert idle["browserRunning"] is False

        worker.session = RunningSession()
        running = await read_binding()
        assert running["browserRunning"] is True
    finally:
        await runner.cleanup()
