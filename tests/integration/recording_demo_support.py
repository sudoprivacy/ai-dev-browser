"""Actual browser journeys and pixel checks used by generated recording tests."""

import asyncio
import itertools
import json
import math
import statistics

from PIL import Image, ImageChops, ImageFilter


def make_page(folder):
    second = folder / "demo-result.html"
    second.write_text(
        """<style>body{margin:0;background:#eef2f7;font:28px sans-serif;padding:40px}</style>
<h1>Request submitted</h1><p>Viewer-friendly recording is ready.</p>""",
        encoding="utf-8",
    )
    first = folder / "demo-form.html"
    first.write_text(
        """<!doctype html><meta charset="utf-8"><title>Recording demo</title>
<style>body{margin:0;background:#eef2f7;color:#334155;font:26px sans-serif;padding:40px}
button,input{font:inherit;padding:12px;background:white;border:1px solid #94a3b8}
#panel{margin-top:24px}#track{position:absolute;left:80px;top:400px;width:500px;height:48px;background:#d1d5db}
#knob{position:absolute;left:0;top:0;width:48px;height:48px;background:#f97316;touch-action:none}
#submit{position:absolute;left:640px;top:480px}#receipt{margin-top:24px}</style>
<h1>New request</h1><button id="open">Open form</button>
<section id="panel" hidden><label>Request name <input id="name"></label><p id="receipt">Waiting for input</p></section>
<div id="track"><div id="knob"></div></div><button id="submit">Submit request</button>
<script>window.moves=[];window.clicks=[];window.inputs=[];window.dragButtons=[];
document.addEventListener('mousemove',e=>moves.push({x:e.clientX,y:e.clientY,t:performance.now(),buttons:e.buttons,trusted:e.isTrusted}));
document.addEventListener('click',e=>clicks.push({id:e.target.id,x:e.clientX,y:e.clientY,trusted:e.isTrusted}));
openButton=document.querySelector('#open');openButton.onclick=()=>document.querySelector('#panel').hidden=false;
document.querySelector('#name').oninput=e=>{inputs.push({value:e.target.value,t:performance.now(),trusted:e.isTrusted});document.querySelector('#receipt').textContent=e.target.value};
const knob=document.querySelector('#knob');let held=false,origin=0;
knob.onpointerdown=e=>{held=true;origin=e.clientX-knob.offsetLeft;knob.setPointerCapture(e.pointerId)};
knob.onpointermove=e=>{if(held){dragButtons.push(e.buttons);knob.style.left=Math.max(0,Math.min(452,e.clientX-origin))+'px'}};
knob.onpointerup=()=>held=false;
document.querySelector('#submit').onclick=()=>location.href='demo-result.html';</script>""",
        encoding="utf-8",
    )
    return first.as_uri(), second.as_uri()


def js(cli, port, expression, *flags):
    return cli("js_evaluate", "--port", port, *flags, "--expression", expression)[
        "result"
    ]


def decode(saved, output, click=None, viewport=None, anchor=None):
    """Inspect actual GIF frames, including output pixels unrelated to the DOM."""
    frames = []
    with Image.open(saved["path"]) as gif:
        assert gif.n_frames == saved["frames"]
        for index in range(gif.n_frames):
            gif.seek(index)
            frame = gif.convert("RGB")
            frames.append(frame)
    assert len(frames) > 5
    blue_counts = [
        sum(
            count
            for count, color in frame.getcolors(frame.width * frame.height)
            if color[2] > 180 and color[2] - color[0] > 45 and color[2] - color[1] > 25
        )
        for frame in frames
    ]
    assert max(blue_counts) > 50, "GIF has no visible blue feedback"
    if click is None:
        folders = [
            output / "recordings" / saved["recording_id"],
            output.parent / "recordings" / saved["recording_id"],
        ]
        recording = next(
            folder for folder in folders if (folder / "viewport.json").is_file()
        )
        viewport = json.loads((recording / "viewport.json").read_text())
        released = [
            json.loads(line)
            for path in (recording / "events").glob("*.jsonl")
            for line in path.read_text().splitlines()
            if json.loads(line)["type"] == "mouseReleased"
        ]
        event = max(released, key=lambda event: event["time"])
        click = event["x"], event["y"]
        viewport = viewport["width"], viewport["height"]
    scale = min(frames[0].width / viewport[0], frames[0].height / viewport[1])
    cx = (frames[0].width - viewport[0] * scale) / 2 + click[0] * scale
    cy = (frames[0].height - viewport[1] * scale) / 2 + click[1] * scale
    radii = []
    centers = []
    for index, frame in enumerate(frames):
        if anchor is not None:
            # Observe the fixture's static track in the actual page pixels.
            # Chrome can change screencast size while switching tabs; the final
            # viewport is not the coordinate transform for every earlier frame.
            landmarks = []
            for color in ((249, 115, 22), (209, 213, 219)):
                masks = [
                    channel.point(
                        [255 if abs(value - target) < 10 else 0 for value in range(256)]
                    )
                    for channel, target in zip(frame.split(), color)
                ]
                landmarks.append(
                    ImageChops.multiply(
                        masks[0], ImageChops.multiply(masks[1], masks[2])
                    )
                )
            # Palette/subpixel text fringes can have the same orange hue. Require
            # a solid patch before locating the calibration rectangle.
            knob = landmarks[0].filter(ImageFilter.MinFilter(5)).getbbox()
            assert knob is not None, ("Page landmark missing from GIF", index)
            row = (knob[1] + knob[3]) // 2
            region = (max(0, knob[0] - 5), row, frame.width, row + 1)
            local = ImageChops.lighter(*landmarks).crop(region).getbbox()
            assert local is not None, ("Page landmark missing from GIF", index)
            bounds = (
                local[0] + region[0],
                knob[1],
                local[2] + region[0],
                knob[3],
            )
            # The long edge minimizes rounding error; GIF fitting is uniform.
            sx = sy = (bounds[2] - bounds[0]) / anchor[2]
            cx = (bounds[0] + bounds[2]) / 2 + (
                click[0] - anchor[0] - anchor[2] / 2
            ) * sx
            cy = (bounds[1] + bounds[3]) / 2 + (
                click[1] - anchor[1] - anchor[3] / 2
            ) * sy
        centers.append([cx, cy])
        distances = []
        # Left of the cursor and pressed halo: a growing ring must be visible,
        # not merely blue glyph fringes, the arrow, or a stationary press cue.
        for y in range(max(0, round(cy - 40)), min(frame.height, round(cy + 41))):
            for x in range(max(0, round(cx - 40)), min(frame.width, round(cx - 10))):
                color = frame.getpixel((x, y))
                baseline = frames[0].getpixel((x, y))
                if (
                    color[2] > 180
                    and color[2] - color[0] > 45
                    and color[2] - color[1] > 25
                    and max(abs(a - b) for a, b in zip(color, baseline)) >= 20
                ):
                    distances.append(math.dist((x, y), (cx, cy)))
        if len(distances) >= 8:
            radii.append((index, statistics.median(distances)))
    (output / "click-ring-evidence.json").write_text(
        json.dumps(
            {
                "center": [cx, cy],
                "frame_centers": centers,
                "anchor": anchor,
                "radii": radii,
            }
        ),
        encoding="utf-8",
    )
    assert any(
        later[1] - earlier[1] > 3
        for i, earlier in enumerate(radii)
        for later in radii[i + 1 :]
    ), ("No expanding click ring at acknowledged click coordinates", (cx, cy), radii)
    samples = sorted(
        {
            0,
            blue_counts.index(max(blue_counts)),
            radii[-1][0],
            len(frames) // 2,
            len(frames) - 1,
        }
    )
    for index in samples:
        frames[index].save(output / f"demo-frame-{index:04d}.png")
    return frames, blue_counts


def run_demo_journey(cli, port, folder):
    first, second = make_page(folder)
    cli("window_set", "--port", port, "--width", 960, "--height", 640)
    cli("page_goto", "--port", port, "--url", first)
    recording = cli("page_record_start", "--port", port, "--out", folder / "demo.gif")
    assert recording["demo"] is True
    try:
        cli("mouse_move", "--port", port, "--x", 100, "--y", 100)
        js(cli, port, "moves=[];true")
        cli("mouse_move", "--port", port, "--x", 400, "--y", 100)
        moved = js(cli, port, "moves")
        assert len(moved) >= 8 and moved[0]["x"] >= 85 and moved[0]["y"] >= 85, moved
        assert moved[-1]["x"] == 400 and moved[-1]["y"] == 100
        assert moved[-1]["t"] - moved[0]["t"] >= 300
        assert all(event["trusted"] for event in moved)
        js(cli, port, "moves=[];true")
        assert cli("mouse_click", "--port", port, "--x", 500, "--y", 180, "--no-move")[
            "clicked"
        ]
        skipped = js(cli, port, "({moves,click:clicks.at(-1)})")
        # Chrome may deliver one positioning event with its press. An explicit
        # --no-move must not produce the demo's interpolated move sequence.
        assert len(skipped["moves"]) <= 1, skipped
        assert skipped["click"]["x"] == 500 and skipped["click"]["y"] == 180
        assert skipped["click"]["trusted"] is True
        opened = cli("click_by_html_id", "--port", port, "--html-id", "open")
        assert opened["clicked"] and js(
            cli, port, "!document.querySelector('#panel').hidden"
        )
        cli("click_by_html_id", "--port", port, "--html-id", "name")
        typed = cli(
            "type_by_text",
            "--port",
            port,
            "--name",
            "Request name",
            "--text",
            "Demo ready",
        )
        assert typed["typed"] and typed["verified"] and typed["method"] == "human", (
            typed
        )
        inputs = js(cli, port, "inputs.filter(e=>e.trusted)")
        assert [event["value"] for event in inputs] == [
            "Demo ready"[:i] for i in range(1, 11)
        ], inputs
        assert all(b["t"] - a["t"] >= 75 for a, b in itertools.pairwise(inputs)), inputs
        cli(
            "mouse_drag",
            "--port",
            port,
            "--from-x",
            104,
            "--from-y",
            424,
            "--to-x",
            324,
            "--to-y",
            424,
        )
        state = js(
            cli,
            port,
            "({left:document.querySelector('#knob').offsetLeft,buttons:dragButtons,clicks})",
        )
        assert state["left"] == 220 and set(state["buttons"]) == {1}, state
        assert all(click["trusted"] for click in state["clicks"])
        assert sum(c["id"] == "open" for c in state["clicks"]) == 1
        # Resize, navigate through a real trusted click, then move in the new
        # document using the prior physical viewport position.
        cli("window_set", "--port", port, "--width", 1200, "--height", 800)
        submitted = cli("click_by_html_id", "--port", port, "--html-id", "submit")
        assert submitted["clicked"] and submitted["url_after"] == second, submitted
        cli("mouse_move", "--port", port, "--x", 100, "--y", 240)
        size = js(cli, port, "[innerWidth,innerHeight]")
        assert size == [1200, 800], size
        screenshot = cli(
            "page_screenshot",
            "--port",
            port,
            "--path",
            folder / "page-only.png",
            "--max-long-edge",
            0,
        )
        saved = cli("page_record_stop", "--recording-id", recording["recording_id"])
    finally:
        # Idempotent stop also checks ownership/lifecycle after assertion errors.
        cli("page_record_stop", "--recording-id", recording["recording_id"])
    assert saved["demo"] and saved["size_bytes"] < 10_000_000
    frames, blue_counts = decode(saved, folder)
    last = frames[-1]
    factor = min(last.width / 1200, last.height / 800)
    x = (last.width - 1200 * factor) / 2 + 100 * factor
    y = (last.height - 800 * factor) / 2 + 240 * factor
    # Cursor interior is white on the otherwise gray empty page region.
    assert (
        max(
            abs(a - b)
            for a, b in zip(
                last.getpixel((round(x + 4), round(y + 11))), (255, 255, 255)
            )
        )
        < 12
    )
    with Image.open(screenshot["path"]) as page:
        assert (
            max(
                abs(a - b)
                for a, b in zip(
                    page.convert("RGB").getpixel((104, 251)), (238, 242, 247)
                )
            )
            < 3
        )
    evidence = {
        "recording": recording,
        "saved": saved,
        "moves": moved,
        "inputs": inputs,
        "page_state": state,
        "viewport": size,
        "blue_pixels": blue_counts,
    }
    (folder / "demo-evidence.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
    return saved


def run_opt_out(cli, port, folder):
    first, _ = make_page(folder)
    cli("window_set", "--port", port, "--width", 960, "--height", 640)
    cli("page_goto", "--port", port, "--url", first)
    recording = cli(
        "page_record_start", "--port", port, "--no-demo", "--out", folder / "plain.gif"
    )
    assert recording["demo"] is False
    cli("click_by_html_id", "--port", port, "--html-id", "open")
    typed = cli(
        "type_by_text",
        "--port",
        port,
        "--name",
        "Request name",
        "--text",
        "Plain capture",
    )
    assert typed["method"] == "insertText" and typed["verified"]
    cli("mouse_move", "--port", port, "--x", 700, "--y", 100)
    saved = cli("page_record_stop", "--recording-id", recording["recording_id"])
    assert saved["demo"] is False
    with Image.open(saved["path"]) as gif:
        gif.seek(gif.n_frames - 1)
        assert gif.convert("RGB").getpixel((704, 111)) == (238, 242, 247)
    (folder / "plain-evidence.json").write_text(
        json.dumps({"saved": saved, "typed": typed}), encoding="utf-8"
    )


async def run_extension_demo(extension, folder):
    """The bundled extension must share the same input pacing and GIF graphics."""
    from ai_dev_browser import core

    first, _ = make_page(folder)
    await extension.call(core.page_goto, url=first)
    recording = await extension.call(
        core.page_record_start, out=str(folder / "extension.gif")
    )
    try:
        await extension.call(core.mouse_move, x=100, y=100)
        await extension.call(core.js_evaluate, expression="moves=[];true")
        await extension.call(core.mouse_move, x=400, y=100)
        moves = (await extension.call(core.js_evaluate, expression="moves"))["result"]
        assert len(moves) >= 8 and moves[0]["x"] >= 85 and moves[0]["y"] >= 85, moves
        assert moves[-1]["x"] == 400 and moves[-1]["y"] == 100
        assert moves[-1]["t"] - moves[0]["t"] >= 300
        assert all(event["trusted"] for event in moves)
        assert (await extension.call(core.click_by_html_id, html_id="open"))["clicked"]
        typed = await extension.call(
            core.type_by_text, name="Request name", text="Extension demo"
        )
        assert typed["typed"] and typed["verified"] and typed["method"] == "human", (
            typed
        )
        state = (
            await extension.call(core.js_evaluate, expression="({clicks,inputs})")
        )["result"]
        assert sum(c["id"] == "open" for c in state["clicks"]) == 1
        assert all(c["trusted"] for c in state["clicks"])
        inputs = [event for event in state["inputs"] if event["trusted"]]
        assert [event["value"] for event in inputs] == [
            "Extension demo"[:i] for i in range(1, 15)
        ]
        assert all(b["t"] - a["t"] >= 75 for a, b in itertools.pairwise(inputs))
        saved = await core.page_record_stop(recording["recording_id"])
        assert saved["demo"] is True
        decode(saved, folder)
        (folder / "extension-evidence.json").write_text(
            json.dumps(
                {"saved": saved, "typed": typed, "moves": moves, "state": state},
                indent=2,
            ),
            encoding="utf-8",
        )
    finally:
        await core.page_record_stop(recording["recording_id"])


async def run_delayed_click_demo(port, folder):
    """A real slow mouseup handler must not expire feedback before its ACK."""
    import time

    from ai_dev_browser import core

    first, _ = make_page(folder)
    browser = await core.connect_browser(port=port)
    try:
        tab = await core.get_active_tab(browser)
        await core.window_set(tab, width=960, height=640)
        await core.page_goto(tab, url=first)
        await tab.evaluate("""document.querySelector('#open').addEventListener('mouseup', () => {
            const started = performance.now();
            while (performance.now() - started < 800) {}
            window.handlerDuration = performance.now() - started;
        }); true""")
        viewport = await tab.evaluate("[innerWidth,innerHeight]")
        recording = await core.page_record_start(tab, out=str(folder / "demo.gif"))
        try:
            tick = time.monotonic()
            clicked = await core.click_by_html_id(tab, html_id="open")
            elapsed = time.monotonic() - tick
            state = await tab.evaluate(
                "({clicks,handlerDuration,opened:!document.querySelector('#panel').hidden})"
            )
            assert clicked["clicked"] and state["opened"], (clicked, state)
            assert state["handlerDuration"] >= 790 and elapsed >= 0.8, (elapsed, state)
            assert len(state["clicks"]) == 1 and state["clicks"][0]["trusted"], state
            saved = await core.page_record_stop(recording["recording_id"])
            point = state["clicks"][0]
            decode(saved, folder, click=[point["x"], point["y"]], viewport=viewport)
            (folder / "delayed-click-evidence.json").write_text(
                json.dumps(
                    {"elapsed": elapsed, "state": state, "saved": saved}, indent=2
                ),
                encoding="utf-8",
            )
        finally:
            await core.page_record_stop(recording["recording_id"])
    finally:
        await browser.close()


def run_recording_lifecycle(cli, port, folder):
    """Demo affects only its recorded target, and ordinary input resumes on stop."""
    first, _ = make_page(folder)
    cli("page_goto", "--port", port, "--url", first)
    anchor = js(
        cli,
        port,
        "(()=>{const r=document.querySelector('#track').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()",
        "--tab-url",
        first,
    )
    recording = cli("page_record_start", "--port", port, "--out", folder / "scoped.gif")
    try:
        other_folder = folder / "other-tab"
        other_folder.mkdir()
        other, _ = make_page(other_folder)
        cli("tab_new", "--port", port, "--url", other)
        cli("click_by_html_id", "--port", port, "--tab-url", other, "--html-id", "open")
        ordinary = cli(
            "type_by_text",
            "--port",
            port,
            "--tab-url",
            other,
            "--name",
            "Request name",
            "--text",
            "Other tab",
        )
        assert ordinary["verified"] and ordinary["method"] == "insertText", ordinary
        tabs = cli("tab_list", "--port", port)["tabs"]
        recorded_index = next(tab["id"] for tab in tabs if tab["url"] == first)
        cli("tab_switch", "--port", port, "--tab-id", recorded_index)
        assert (
            js(cli, port, "document.querySelector('#name').value", "--tab-url", first)
            == ""
        )
        cli("click_by_html_id", "--port", port, "--tab-url", first, "--html-id", "open")
        paced = cli(
            "type_by_text",
            "--port",
            port,
            "--tab-url",
            first,
            "--name",
            "Request name",
            "--text",
            "Recorded tab",
        )
        assert paced["verified"] and paced["method"] == "human", paced
        saved = cli("page_record_stop", "--recording-id", recording["recording_id"])
        ordinary_after = cli(
            "type_by_text",
            "--port",
            port,
            "--tab-url",
            first,
            "--name",
            "Request name",
            "--text",
            "After stop",
            "--clear",
        )
        assert (
            ordinary_after["verified"] and ordinary_after["method"] == "insertText"
        ), ordinary_after
        assert (
            js(cli, port, "document.querySelector('#name').value", "--tab-url", first)
            == "After stop"
        )
        decode(saved, folder, anchor=anchor)
    finally:
        cli("page_record_stop", "--recording-id", recording["recording_id"])


async def run_extension_proxy_demo(extension, folder, monkeypatch):
    """An outbound proxy must never receive local extension control or capture."""
    import urllib.error
    import urllib.request

    from aiohttp import web
    import pytest

    from ai_dev_browser.core.ext_bridge import bridge_status, shutdown_bridge
    from .extension_window_support import extension_cli

    requests = []

    async def reject(request):
        requests.append(request.raw_path)
        return web.Response(status=502, text="fixture rejects proxy traffic")

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", reject)
    runner = web.AppRunner(app)
    await runner.setup()
    proxy = web.TCPSite(runner, "127.0.0.1", 0)
    await proxy.start()
    address = f"http://127.0.0.1:{proxy._server.sockets[0].getsockname()[1]}"
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(name, address)
    for name in ("NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": address})
        )
        with pytest.raises(urllib.error.HTTPError) as rejected:
            await asyncio.to_thread(
                opener.open, "http://proxy-check.invalid/", timeout=2
            )
        assert rejected.value.code == 502 and len(requests) == 1
        requests.clear()
        status = await bridge_status(extension.port)
        assert status and status["extension_connected"], {"proxy_requests": requests}
        code, connected = await extension_cli(extension, "browser_connect")
        assert code == 0 and connected["connected"], (code, connected)
        await run_extension_demo(extension, folder)
        # The live fixture's bridge is intentionally unmanaged. Its explicit
        # shutdown refusal must also arrive directly, leaving Chrome usable.
        assert not await shutdown_bridge(extension.port)
        assert (await bridge_status(extension.port))["extension_connected"]
        assert not requests, requests
        (folder / "proxy-control-evidence.json").write_text(
            json.dumps(
                {
                    "outbound_proxy_verified": True,
                    "local_control_proxy_requests": len(requests),
                    "cli_connected": True,
                    "recording_saved": True,
                    "unmanaged_shutdown_refused": True,
                }
            ),
            encoding="utf-8",
        )
    finally:
        await runner.cleanup()


async def run_slow_capture_health(extension, folder, monkeypatch):
    """Delay delivery of real Chrome health replies without blocking input/events."""
    from websockets.exceptions import ConnectionClosedOK

    from ai_dev_browser import core

    first, _ = make_page(folder)
    await extension.call(core.page_goto, url=first)
    forward = extension.bridge._forward
    pending = []
    observed = asyncio.Event()
    receipts = []
    armed = False

    class DelayedReply:
        def __init__(self, ws):
            self.ws = ws

        async def send(self, raw):
            response = json.loads(raw)
            assert "cssLayoutViewport" in response["result"], response
            receipts.append({"real_layout_reply": True, "delay_seconds": 0.8})
            observed.set()

            async def deliver():
                await asyncio.sleep(0.8)
                try:
                    await self.ws.send(raw)
                except ConnectionClosedOK:
                    # Successful stop closes the recorder with one background
                    # read potentially pending; preserve abnormal close errors.
                    pass

            task = asyncio.create_task(deliver())
            pending.append(task)

    async def delayed_forward(ws, target_id, raw, expected_session=None):
        if armed and json.loads(raw).get("method") == "Page.getLayoutMetrics":
            ws = DelayedReply(ws)
        await forward(ws, target_id, raw, expected_session)

    monkeypatch.setattr(extension.bridge, "_forward", delayed_forward)
    point = (
        await extension.call(
            core.js_evaluate,
            expression="""(() => {
        const r = document.querySelector('#open').getBoundingClientRect();
        return [r.x + r.width / 2, r.y + r.height / 2];
    })()""",
        )
    )["result"]
    recording = await extension.call(
        core.page_record_start, out=str(folder / "slow-health.gif")
    )
    try:
        armed = True
        await asyncio.wait_for(observed.wait(), 5)
        # Complete a real click while the unrelated read-only health response
        # is pending. Its 550ms overlay must keep advancing at the normal FPS.
        await extension.call(core.mouse_click, x=point[0], y=point[1], move=False)
        state = (
            await extension.call(
                core.js_evaluate,
                expression="({clicks,opened:!document.querySelector('#panel').hidden})",
            )
        )["result"]
        assert state["opened"] and len(state["clicks"]) == 1, state
        assert state["clicks"][0]["trusted"], state
        saved = await core.page_record_stop(recording["recording_id"])
        assert saved["saved"], saved
        (folder / "slow-health-evidence.json").write_text(
            json.dumps({"health_replies": receipts, "page": state}), encoding="utf-8"
        )
        decode(saved, folder)
    finally:
        await core.page_record_stop(recording["recording_id"])
        if pending:
            await asyncio.gather(*pending)


async def run_failed_movement(port, folder, monkeypatch):
    """A failed optional positioning move must leave the real trusted click usable."""
    from ai_dev_browser import core
    from ai_dev_browser.core import human

    first, _ = make_page(folder)
    browser = await core.connect_browser(port=port)
    recording = None
    try:
        tab = await core.get_active_tab(browser)
        await core.page_goto(tab, url=first)
        recording = await core.page_record_start(
            tab, out=str(folder / "failed-move.gif")
        )
        attempts = []

        async def failed_move(*args, **kwargs):
            attempts.append(True)
            raise TimeoutError("Injected positioning timeout")

        monkeypatch.setattr(human, "mouse_move", failed_move)
        assert await core.mouse_click(tab, x=117, y=216) is True
        state = await tab.evaluate(
            "({clicks,opened:!document.querySelector('#panel').hidden})"
        )
        assert len(attempts) == 1 and state["opened"], state
        assert len(state["clicks"]) == 1 and state["clicks"][0]["trusted"], state
        saved = await core.page_record_stop(recording["recording_id"])
        decode(saved, folder)
    finally:
        if recording:
            await core.page_record_stop(recording["recording_id"])
        await browser.close()
