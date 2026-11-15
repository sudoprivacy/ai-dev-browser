"""Additive observers keep the existing page owner and transport lifecycle."""

import aiohttp
from aiohttp import web

from ai_dev_browser.remote.cdp import CDP


async def test_observer_does_not_replace_owner_or_close_its_socket():
    received, observed = [], []

    async def socket(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for message in ws:
            if message.type != aiohttp.WSMsgType.TEXT:
                break
            command = message.json()
            await ws.send_json(
                {"method": "Page.javascriptDialogOpening", "params": {"type": "alert"}}
            )
            await ws.send_json({"id": command["id"], "result": {"ack": True}})
        return ws

    app = web.Application()
    app.router.add_get("/page", socket)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with aiohttp.ClientSession() as http:
            page = CDP(
                await http.ws_connect(f"http://127.0.0.1:{port}/page"),
                lambda method, params: received.append((method, params)),
            )

            def observe(method, params):
                observed.append((method, params))

            page.add_event_handler(observe)
            page.add_event_handler(observe)
            assert await page.call("Page.enable") == {"ack": True}
            assert observed == received and len(observed) == 1
            assert page.remove_event_handler(observe) is True
            assert page.remove_event_handler(observe) is False
            assert await page.call("Page.enable") == {"ack": True}
            assert len(received) == 2 and len(observed) == 1
            assert not page.reader.done()
            await page.close()
            assert page.reader.done() and not page.pending
    finally:
        await runner.cleanup()
