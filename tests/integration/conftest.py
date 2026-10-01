"""Real browser fixtures for generated CLI / extension workflow tests."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ai_dev_browser.cdp import runtime, service_worker, target as cdp_target
from ai_dev_browser.core import connect_browser, get_active_tab
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import BrowserClient
from ai_dev_browser.core.ext_bridge import _Bridge
from ai_dev_browser.core.extension import extension_dir


@pytest.fixture
def cli(tmp_path):
    """Every invocation is a fresh process, with stdout/stderr checked separately."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("AI_DEV_BROWSER_")}
    for name in ("AI_DEV_BROWSER_CHROME", "AI_DEV_BROWSER_STARTUP_TIMEOUT"):
        if name in os.environ:
            env[name] = os.environ[name]
    env["AI_DEV_BROWSER_RECORDING_DIR"] = str(tmp_path / "recordings")

    def invoke(tool, *args, exit_code=0):
        command = [
            sys.executable,
            "-m",
            f"ai_dev_browser.tools.{tool}",
            *map(str, args),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            stdin=subprocess.DEVNULL,
            timeout=120,
        )
        assert result.stdout.strip(), (command, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        print(f"CLI {tool}: exit={result.returncode} {payload}", flush=True)
        assert result.returncode == exit_code, (command, payload, result.stderr)
        return payload

    return invoke


@pytest.fixture
def recording_browser(cli):
    result = cli("browser_start", "--headless", "True", "--temp", "--silent-stderr")
    try:
        yield result["port"]
    finally:
        cli("browser_stop", "--port", result["port"])


@pytest.fixture
def recording_page(tmp_path):
    """A visible interaction, animation and navigation with trusted input evidence."""
    first = tmp_path / "record-first.html"
    second = tmp_path / "record-second.html"
    second.write_text(
        "<style>body{margin:0;background:#eebb22;font:36px sans-serif;padding:60px}</style>"
        '<h1>Request submitted</h1><p id="done">Review complete</p>',
        encoding="utf-8",
    )
    first.write_text(
        """<!doctype html><meta charset="utf-8"><title>Recording acceptance</title>
<style>body{margin:0;background:#2244aa;color:white;font:32px sans-serif;padding:60px}
button,input,a{font:inherit;padding:12px}#panel{background:#227744;padding:20px}
body.open{background:#227744;transition:background .6s}a{color:white}</style>
<h1>New request</h1><button id="open">Open form</button>
<section id="panel" hidden><label>Request name <input id="name"></label>
<p id="preview">Enter a name</p><a id="next" href="record-second.html">Submit request</a></section>
<script>window.trusted=[];document.querySelector('#open').onclick=e=>{
trusted.push(e.isTrusted);document.body.classList.add('open');document.querySelector('#panel').hidden=false};
document.querySelector('#name').oninput=e=>{trusted.push(e.isTrusted);document.querySelector('#preview').textContent=e.target.value};
</script>""",
        encoding="utf-8",
    )
    return first.as_uri(), second.as_uri()


@pytest.fixture
def inspect_recording():
    """Decode every GIF frame: assert visible state order and real elapsed time."""
    from PIL import Image

    def inspect(result, expected_colors, minimum_duration=0):
        path = Path(result["path"])
        assert result["saved"] and path.stat().st_size == result["size_bytes"]
        assert result["size_bytes"] <= 10_000_000
        colors = []
        duration = 0
        with Image.open(path) as gif:
            assert gif.format == "GIF" and gif.n_frames == result["frames"]
            assert gif.size == (result["width"], result["height"])
            assert gif.width <= 1280 and gif.height <= 720
            for index in range(gif.n_frames):
                gif.seek(index)
                duration += gif.info.get("duration", 0)
                frame = gif.convert("RGB")
                # A resize/navigation can add letterboxing to the fixed canvas.
                # The page's dominant background identifies its visible state;
                # a corner pixel could be padding rather than page content.
                pixel = max(frame.getcolors(frame.width * frame.height))[1]
                colors.append(pixel)
                frame.save(path.with_name(f"frame-{index:04d}.png"))
        assert abs(duration / 1000 - result["duration_seconds"]) < 0.011
        assert duration / 1000 >= minimum_duration, (duration, minimum_duration)
        cursor = 0
        for color in expected_colors:
            while (
                cursor < len(colors)
                and max(abs(a - b) for a, b in zip(colors[cursor], color)) > 8
            ):
                cursor += 1
            assert cursor < len(colors), (color, colors)
            cursor += 1
        return colors

    return inspect


@pytest.fixture(params=["True", "False", "new", "old"])
def cli_browser(request, cli):
    if (
        request.param == "False"
        and sys.platform == "linux"
        and not os.environ.get("DISPLAY")
    ):
        pytest.skip("Windowed Chrome needs DISPLAY on Linux")
    started = []

    def start():
        result = cli("browser_start", "--headless", request.param, "--silent-stderr")
        assert result["headless"] == {"True": True, "False": False}.get(
            request.param, request.param
        )
        started.append(result["port"])
        return result["port"]

    try:
        yield start
    finally:
        for port in started:
            cli("browser_stop", "--port", port)


@pytest.fixture
def click_page(tmp_path):
    """Visible state and trusted-event evidence, served from an isolated file."""
    path = tmp_path / "click.html"
    path.write_text(
        """<!doctype html><meta charset="utf-8">
<title>Click acceptance</title>
<style>body { font:24px sans-serif; margin:32px; background:#eef2f7 }
button { font:inherit; padding:20px; background:#fff } #result { margin-top:24px }</style>
<button id="action">Click once</button><div id="result">Waiting</div>
<script>
window.clicks=[];
document.getElementById('action').addEventListener('click', e=>{
  window.clicks.push({trusted:e.isTrusted, x:e.clientX, y:e.clientY});
  document.getElementById('result').textContent='Clicked '+window.clicks.length+' (trusted='+e.isTrusted+')';
});
</script>""",
        encoding="utf-8",
    )
    return path.as_uri()


async def _until(predicate, message, timeout=10):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.05)

    try:
        await asyncio.wait_for(poll(), timeout)
    except asyncio.TimeoutError:
        pytest.fail(message)


class _LiveExtension:
    def __init__(self, port, chrome_port, bridge):
        self.port = port
        self.chrome_port = chrome_port
        self.bridge = bridge

    async def call(self, function, **kwargs):
        # Fresh acquisition each time, matching the CLI's per-call lifetime.
        browser = await BrowserClient.connect(
            "127.0.0.1",
            self.port,
            ws_url=f"ws://127.0.0.1:{self.port}/devtools/browser",
        )
        browser.transport = "extension"
        try:
            tab = await get_active_tab(browser)
            result = await function(tab, **kwargs)
            print(f"EXT {function.__name__}: {result}", flush=True)
            return result
        finally:
            await browser.close()

    async def restart_worker(self):
        # Control only this test's isolated Chrome. Identify our worker by its
        # bridge endpoint: machine policy may also load unrelated extensions.
        # Disconnect the inspection session before forcing worker termination.
        browser = await connect_browser(port=self.chrome_port)
        try:
            control = browser.tabs[0]
            worker = None
            for candidate in browser.targets:
                if candidate.type_ != "service_worker":
                    continue
                try:
                    value, error = await candidate._connection.send(
                        runtime.evaluate(
                            "typeof BRIDGE === 'string' ? BRIDGE : null",
                            return_by_value=True,
                        )
                    )
                    if error is None and value.value == f"ws://127.0.0.1:{self.port}":
                        worker = candidate.target
                        break
                finally:
                    await candidate._connection.disconnect()
            assert worker is not None, "test extension worker not found"
            print(f"EXT stopping worker {worker.url}", flush=True)
            old_connection = self.bridge.extension
            # Target.closeTarget is Chrome's documented extension-worker
            # termination path. Wait for the actual disconnect before waking it.
            assert await browser.connection.send(
                cdp_target.close_target(worker.target_id)
            )
            await _until(
                lambda: self.bridge.extension is not old_connection,
                "worker did not disconnect",
            )
            await control.send(service_worker.enable())
            await control.send(
                service_worker.start_worker(worker.url.rsplit("/", 1)[0] + "/"),
                _is_update=True,
            )
            await _until(
                lambda: self.bridge.extension is not None, "worker did not reconnect"
            )
            print("EXT worker stopped and restarted", flush=True)
        finally:
            await browser.close()


@pytest.fixture(params=["legacy", "asyncio"])
async def live_extension(request, tmp_path, monkeypatch):
    """Real bundled extension on both supported WS backends; no fake Chrome APIs.

    Set AI_DEV_BROWSER_TEST_EXTENSION_CHROME to Chrome for Testing / Chromium.
    The regular branded browser no longer supports --load-extension. CI provides
    the binary explicitly; this test never loads anything into a user's profile.
    """
    binary = os.environ.get("AI_DEV_BROWSER_TEST_EXTENSION_CHROME")
    if not binary:
        pytest.skip(
            "Set AI_DEV_BROWSER_TEST_EXTENSION_CHROME to run the real extension"
        )
    assert Path(binary).is_file(), binary
    monkeypatch.setenv("AI_DEV_BROWSER_CHROME", binary)
    if request.param == "legacy":
        from websockets.legacy.server import serve
    else:
        from websockets.asyncio.server import serve

    bridge = _Bridge()
    server = await serve(bridge.handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    # Only the endpoint changes, isolating this test from a user's live bridge.
    copied_extension = tmp_path / "extension"
    shutil.copytree(extension_dir(), copied_extension)
    background = copied_extension / "background.js"
    source = background.read_text(encoding="utf-8")
    assert source.count("127.0.0.1:9522") == 1
    background.write_text(
        source.replace("127.0.0.1:9522", f"127.0.0.1:{port}"), encoding="utf-8"
    )
    chrome = None
    try:
        chrome = await asyncio.to_thread(
            browser_start,
            headless=True,
            temp=True,
            silent_stderr=True,
            override_default_args={"--disable-extensions": None},
            extra_args=[
                f"--load-extension={copied_extension}",
                f"--disable-extensions-except={copied_extension}",
                "--no-sandbox",
            ],
        )
        assert "error" not in chrome, chrome
        await _until(lambda: bridge.extension is not None, "extension did not connect")
        yield _LiveExtension(port, chrome["port"], bridge)
    finally:
        if chrome and "port" in chrome:
            await asyncio.to_thread(browser_stop, port=chrome["port"])
        server.close()
        await server.wait_closed()
