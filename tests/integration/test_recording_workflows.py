#!/usr/bin/env python3
"""
AUTO-GENERATED - DO NOT EDIT

This file was auto-generated from SKILL.md by integration-test-generator.
Generated: 2026-10-08 13:41:05

To modify test behavior:
  1. Update SKILL.md with better workflow examples
  2. Use integration-test-generator skill to regenerate

Manual edits will be lost when regenerated!

Coverage: 8/8 real workflows (100%)
Identified using AI scenario recognition with complete code generation

Coverage Report:
  ✅ Start -> record form opening and typing -> navigate -> stop -> decode GIF
  ✅ Record -> reject duplicate and invalid output -> close tab -> stop fails -> record again
  ✅ Record -> leave capture beyond limit -> stop reports incomplete -> start again
  ✅ Real extension record -> trusted click on separate connection -> navigate -> decode -> worker loss fails
  ✅ Start -> obstruct destination -> stop -> inspect failure
  ✅ Open -> record -> type -> submit -> inspect article -> stop -> decode
  ✅ Start -> kill own recorder -> stop -> recover
  ✅ Start -> animate -> exceed limit -> reject partial -> recover

Uncovered workflows: None
"""

# Standard library imports
import os
from pathlib import Path

# Third-party imports
import pytest

# Skill-specific imports
# Source: tests/integration/scenarios_recording.json (integration-test-generator)
import asyncio
import json
import time
from ai_dev_browser.core import (
    click_by_ref,
    page_record_start,
    page_record_stop,
    page_goto,
    page_wait_element,
    js_evaluate,
)
from ai_dev_browser.core.errors import RecordingError
import ai_dev_browser.tools as tool_package

# Integration guard: allow CI to opt-out with SKIP_INTEGRATION=1
SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    """Skip if SKIP_INTEGRATION is set."""
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set — skipping integration tests")


def test_recording_cli_interaction_navigation_and_idle(
    cli, recording_browser, recording_page, tmp_path, inspect_recording
):
    """
    Real scenario: Start -> record form opening and typing -> navigate -> stop -> decode GIF

    Workflow: Start -> record form opening and typing -> navigate -> stop -> decode GIF

    User problem: Share a complete before-change workflow recorded across independent CLI processes, including time on a static page.

    Data flow:
      1. Discover recording from the installed tool listing and screenshot help, then use its documented start/stop workflow
      2. inline code operation
      3. inline code operation
      4. inline code operation
      5. Play the saved GIF in Chrome and verify actual animated pixels, based on live acceptance
    """
    # Step 1: Discover recording from the installed tool listing and screenshot help, then use its documented start/stop workflow
    tool_dir = Path(tool_package.__file__).parent
    assert (tool_dir / "page_record_start.py").is_file() and (
        tool_dir / "page_record_stop.py"
    ).is_file()
    screenshot_help = cli("page_screenshot", "--help")
    assert (
        "page_record_start" in screenshot_help and "page_record_stop" in screenshot_help
    )
    start_help = cli("page_record_start", "--help")
    stop_help = cli("page_record_stop", "--help")
    assert (
        "before/after recording" in start_help
        and "recording_id" in start_help
        and "page_record_stop" in start_help
    )
    assert (
        "--fps" in start_help
        and "--out" in start_help
        and "--max-duration" in start_help
    )
    assert (
        start_help.count("Maximum output frames per second") == 1
        and "Args:" not in start_help
        and "Failure:" not in start_help
    )
    assert (
        "--recording-id" in stop_help
        and "--port" not in stop_help
        and "--transport" not in stop_help
    )
    (tmp_path / "tool-help.txt").write_text(
        screenshot_help + start_help + stop_help, encoding="utf-8"
    )

    # Step 2: Execute operation
    port = recording_browser
    first, second = recording_page
    assert cli("page_goto", "--port", port, "--url", first)["success"]
    out = tmp_path / "workflow.gif"
    recording = cli("page_record_start", "--port", port, "--fps", 10, "--out", out)
    assert recording["recording"] and not out.exists()
    began = time.monotonic()

    # Step 3: Execute operation
    button = cli("page_wait_element", "--port", port, "--selector", "#open")
    assert cli("click_by_ref", "--port", port, "--ref", button["ref"])["clicked"]
    field = cli("page_wait_element", "--port", port, "--selector", "#name")
    assert cli(
        "type_by_ref",
        "--port",
        port,
        "--ref",
        field["ref"],
        "--text",
        "Recorded request",
        "--keystrokes",
    )["verified"]
    state = cli(
        "js_evaluate",
        "--port",
        port,
        "--expression",
        "({text:document.querySelector('#preview').textContent,trusted:window.trusted})",
    )["result"]
    assert (
        state["text"] == "Recorded request"
        and state["trusted"][0] is True
        and len(state["trusted"]) >= 17
        and all(state["trusted"][-16:])
    ), state

    # Step 4: Execute operation
    assert cli("page_goto", "--port", port, "--url", second)["url"] == second
    time.sleep(1.2)
    assert not out.exists()
    elapsed = time.monotonic() - began
    saved = cli("page_record_stop")
    assert saved["recording_id"] == recording["recording_id"]
    assert Path(saved["path"]).is_file()
    colors = inspect_recording(
        saved, [(34, 68, 170), (34, 119, 68), (238, 187, 34)], elapsed - 0.2
    )
    assert len(colors) >= 4, colors
    assert cli("page_record_stop", "--recording-id", recording["recording_id"]) == saved
    (tmp_path / "evidence.json").write_text(
        json.dumps(
            {"started": recording, "saved": saved, "trusted": state, "colors": colors}
        ),
        encoding="utf-8",
    )

    # Step 5: Play the saved GIF in Chrome and verify actual animated pixels, based on live acceptance
    from PIL import Image, ImageChops

    assert cli("page_goto", "--port", port, "--url", Path(saved["path"]).as_uri())[
        "success"
    ]
    image = cli("page_wait_element", "--port", port, "--selector", "img")
    assert image["found"]
    cli("page_screenshot", "--port", port, "--path", tmp_path / "playback-before.png")
    with Image.open(tmp_path / "playback-before.png") as frame:
        before = frame.convert("RGB")
    deadline = time.monotonic() + saved["duration_seconds"] + 5
    while True:
        time.sleep(0.3)
        cli(
            "page_screenshot", "--port", port, "--path", tmp_path / "playback-after.png"
        )
        with Image.open(tmp_path / "playback-after.png") as frame:
            after = frame.convert("RGB")
        if ImageChops.difference(before, after).getbbox():
            break
        assert time.monotonic() < deadline, "Saved GIF did not animate in Chrome"


def test_recording_cli_conflict_and_closed_tab(
    cli, recording_browser, recording_page, tmp_path, inspect_recording
):
    """
    Real scenario: Record -> reject duplicate and invalid output -> close tab -> stop fails -> record again

    Workflow: Record -> reject duplicate and invalid output -> close tab -> stop fails -> record again

    User problem: A broken recording must never be published or misreported as a successful file, and locks must be released for recovery.

    Data flow:
      1. inline code operation
      2. inline code operation
      3. inline code operation
    """
    # Step 1: Execute operation
    port = recording_browser
    first, second = recording_page
    cli("page_goto", "--port", port, "--url", first)
    for args in [
        ("--fps", 0),
        ("--out", tmp_path / "bad.mp4"),
        ("--max-duration", "nan"),
    ]:
        bad = cli("page_record_start", "--port", port, *args, exit_code=2)
        assert (
            bad["error_code"] == "validation"
            and bad["retryable"] is False
            and bad["hint"]
        )
    existing = tmp_path / "existing.gif"
    existing.write_bytes(b"preserve me")
    assert (
        cli("page_record_start", "--port", port, "--out", existing, exit_code=5)[
            "error_code"
        ]
        == "conflict"
    )
    assert existing.read_bytes() == b"preserve me"
    out = tmp_path / "interrupted.gif"
    recording = cli("page_record_start", "--port", port, "--out", out)

    # Step 2: Execute operation
    duplicate = cli(
        "page_record_start",
        "--port",
        port,
        "--out",
        tmp_path / "duplicate.gif",
        exit_code=5,
    )
    assert duplicate["error_code"] == "conflict" and duplicate["retryable"] is False
    cli("tab_new", "--port", port, "--url", second)
    tabs = cli("tab_list", "--port", port)["tabs"]
    closing = next(t["id"] for t in tabs if t["url"] == first)
    assert cli("tab_close", "--port", port, "--tab-id", closing)["closed"]
    failed = cli(
        "page_record_stop", "--recording-id", recording["recording_id"], exit_code=1
    )
    assert (
        failed["error_code"] == "recording_failed"
        and failed["retryable"] is False
        and failed["hint"]
    ), failed
    assert not out.exists() and not list(tmp_path.glob("*.partial"))

    # Step 3: Execute operation
    cli("page_goto", "--port", port, "--url", second)
    restarted = cli(
        "page_record_start", "--port", port, "--out", tmp_path / "recovered.gif"
    )
    saved = cli("page_record_stop", "--recording-id", restarted["recording_id"])
    inspect_recording(saved, [(238, 187, 34)])


def test_recording_cli_duration_limit(cli, recording_browser, recording_page, tmp_path):
    """
    Real scenario: Record -> leave capture beyond limit -> stop reports incomplete -> start again

    Workflow: Record -> leave capture beyond limit -> stop reports incomplete -> start again

    User problem: A forgotten recorder must stop consuming resources and must not silently truncate the output.

    Data flow:
      1. inline code operation
      2. inline code operation
      3. inline code operation
    """
    # Step 1: Execute operation
    port = recording_browser
    cli("page_goto", "--port", port, "--url", recording_page[0])
    out = tmp_path / "limited.gif"
    recording = cli(
        "page_record_start", "--port", port, "--max-duration", 1, "--out", out
    )

    # Step 2: Execute operation
    time.sleep(1.5)
    failed = cli(
        "page_record_stop", "--recording-id", recording["recording_id"], exit_code=1
    )
    assert (
        failed["error_code"] == "recording_failed" and "max_duration" in failed["error"]
    )
    assert not out.exists()

    # Step 3: Execute operation
    restarted = cli(
        "page_record_start", "--port", port, "--out", tmp_path / "after-limit.gif"
    )
    assert cli("page_record_stop", "--recording-id", restarted["recording_id"])["saved"]


async def test_recording_real_extension_concurrent_commands(
    live_extension, recording_page, tmp_path, monkeypatch, inspect_recording
):
    """
    Real scenario: Real extension record -> trusted click on separate connection -> navigate -> decode -> worker loss fails

    Workflow: Real extension record -> trusted click on separate connection -> navigate -> decode -> worker loss fails

    User problem: Recording must retain its event stream while other clients drive the same tab, and reject capture gaps caused by an extension worker restart.

    Data flow:
      1. inline code operation
      2. Stop immediately after navigation; the saved final frame must show the destination page
      3. inline code operation
    """
    # Step 1: Execute operation
    monkeypatch.setenv("AI_DEV_BROWSER_RECORDING_DIR", str(tmp_path / "recordings"))
    first, second = recording_page
    await live_extension.call(page_goto, url=first)
    recording = await live_extension.call(
        page_record_start, out=str(tmp_path / "extension.gif")
    )
    assert recording["recording"]

    # Step 2: Stop immediately after navigation; the saved final frame must show the destination page
    button = await live_extension.call(page_wait_element, selector="#open")
    assert (await live_extension.call(click_by_ref, ref=button["ref"]))["clicked"]
    assert (await live_extension.call(js_evaluate, expression="window.trusted"))[
        "result"
    ] == [True]
    await asyncio.sleep(0.8)
    await live_extension.call(page_goto, url=second)
    saved = await page_record_stop(recording["recording_id"])
    colors = inspect_recording(saved, [(34, 68, 170), (34, 119, 68), (238, 187, 34)])
    assert max(abs(a - b) for a, b in zip(colors[-1], (238, 187, 34))) <= 8, (
        "Final navigation frame missing from GIF"
    )

    # Step 3: Execute operation
    interrupted = await live_extension.call(
        page_record_start, out=str(tmp_path / "worker-lost.gif")
    )
    await live_extension.restart_worker()
    with pytest.raises(RecordingError):
        await page_record_stop(interrupted["recording_id"])
    assert not (tmp_path / "worker-lost.gif").exists()
    assert not list(tmp_path.glob("*.partial"))


def test_recording_cli_output_failure(cli, recording_browser, recording_page, tmp_path):
    """
    Real scenario: Record -> output becomes unwritable -> stop fails -> existing data preserved

    Workflow: Start -> obstruct destination -> stop -> inspect failure

    User problem: Concurrent file creation must never be overwritten or mistaken for a completed recording.

    Data flow:
      1. inline code operation
      2. inline code operation
      3. inline code operation
    """
    # Step 1: Execute operation
    port = recording_browser
    cli("page_goto", "--port", port, "--url", recording_page[0])
    out = tmp_path / "occupied.gif"
    recording = cli("page_record_start", "--port", port, "--out", out)

    # Step 2: Execute operation
    out.write_bytes(b"belongs to somebody else")
    failed = cli(
        "page_record_stop", "--recording-id", recording["recording_id"], exit_code=1
    )
    assert failed["error_code"] == "recording_failed" and failed["retryable"] is False

    # Step 3: Execute operation
    assert out.read_bytes() == b"belongs to somebody else"
    assert not list(tmp_path.glob("*.partial"))
    assert (
        cli(
            "page_record_stop", "--recording-id", recording["recording_id"], exit_code=1
        )["error"]
        == failed["error"]
    )


def test_recording_public_web_live(cli, recording_browser, tmp_path):
    """
    Real scenario: Record Wikipedia -> type query -> open article -> stop -> decode real website recording

    Workflow: Open -> record -> type -> submit -> inspect article -> stop -> decode

    User problem: An agent needs to share the actual public website interaction, including page navigation and loading.

    Data flow:
      1. inline code operation
      2. inline code operation
      3. inline code operation
    """
    # Step 1: Execute operation
    if os.environ.get("AI_DEV_BROWSER_LIVE_WEB") != "1":
        pytest.skip("Set AI_DEV_BROWSER_LIVE_WEB=1 for public website recording")
    port = recording_browser
    assert (
        cli("page_goto", "--port", port, "--url", "https://www.wikipedia.org/")["title"]
        == "Wikipedia"
    )
    recording = cli(
        "page_record_start", "--port", port, "--out", tmp_path / "wikipedia.gif"
    )

    # Step 2: Execute operation
    search = cli("page_wait_element", "--port", port, "--selector", "#searchInput")
    typed = cli(
        "type_by_ref",
        "--port",
        port,
        "--ref",
        search["ref"],
        "--text",
        "Google Chrome",
        "--clear",
        "--keystrokes",
    )
    assert typed["typed"] and typed["verified"]
    button = cli(
        "page_wait_element", "--port", port, "--selector", "button[type=submit]"
    )
    assert cli("click_by_ref", "--port", port, "--ref", button["ref"])["clicked"]
    assert cli(
        "page_wait_element",
        "--port",
        port,
        "--selector",
        "#firstHeading",
        "--timeout",
        45,
    )["found"]
    article = cli(
        "js_evaluate",
        "--port",
        port,
        "--expression",
        "({heading:document.getElementById('firstHeading').innerText,url:location.href})",
    )["result"]
    assert (
        "Google Chrome" in article["heading"]
        and "/wiki/Google_Chrome" in article["url"]
    ), article
    time.sleep(1)

    # Step 3: Execute operation
    saved = cli("page_record_stop", "--recording-id", recording["recording_id"])
    from PIL import Image

    with Image.open(saved["path"]) as gif:
        assert gif.n_frames == saved["frames"] and gif.n_frames >= 5
        first = None
        for index in range(gif.n_frames):
            gif.seek(index)
            frame = gif.convert("RGB")
            if index == 0:
                first = frame.tobytes()
            frame.save(tmp_path / f"public-frame-{index:04d}.png")
        assert first != frame.tobytes(), (
            "Recording did not capture the article navigation"
        )
    (tmp_path / "public-evidence.json").write_text(
        json.dumps(
            {"started": recording, "saved": saved, "article": article, "typed": typed}
        ),
        encoding="utf-8",
    )


def test_recording_cli_worker_killed(cli, recording_browser, recording_page, tmp_path):
    """
    Real scenario: Record -> terminate owned worker -> stop fails -> restart recording

    Workflow: Start -> kill own recorder -> stop -> recover

    User problem: A crashed recorder must not leave a permanent lock or publish a truncated animation.

    Data flow:
      1. inline code operation
      2. inline code operation
      3. inline code operation
    """
    # Step 1: Execute operation
    port = recording_browser
    cli("page_goto", "--port", port, "--url", recording_page[0])
    out = tmp_path / "killed.gif"
    recording = cli("page_record_start", "--port", port, "--out", out)

    # Step 2: Execute operation
    import signal

    state_path = tmp_path / "recordings" / recording["recording_id"] / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "recording" and state["pid"] != os.getpid()
    os.kill(state["pid"], signal.SIGTERM)
    failed = cli(
        "page_record_stop", "--recording-id", recording["recording_id"], exit_code=1
    )
    assert failed["error_code"] == "recording_failed" and failed["retryable"] is False
    assert "heartbeat" in failed["error"] and not out.exists()

    # Step 3: Execute operation
    restarted = cli(
        "page_record_start", "--port", port, "--out", tmp_path / "after-crash.gif"
    )
    assert cli("page_record_stop", "--recording-id", restarted["recording_id"])["saved"]


def test_recording_cli_share_size_limit(
    cli, recording_browser, recording_page, tmp_path
):
    """
    Real scenario: Record busy animation -> exceed share limit -> stop fails -> record smaller flow

    Workflow: Start -> animate -> exceed limit -> reject partial -> recover

    User problem: An oversized GIF cannot be previewed in Feishu; the recorder must report that explicitly and avoid publishing a misleading partial.

    Data flow:
      1. inline code operation
      2. inline code operation
      3. inline code operation
    """
    # Step 1: Execute operation
    port = recording_browser
    cli("page_goto", "--port", port, "--url", recording_page[0])
    out = tmp_path / "too-large.gif"
    recording = cli("page_record_start", "--port", port, "--out", out, "--fps", 30)

    # Step 2: Execute operation
    animation = "(() => { document.body.innerHTML='<canvas width=1280 height=720></canvas>'; document.body.style='padding:0;margin:0'; const c=document.querySelector('canvas'),ctx=c.getContext('2d'),img=ctx.createImageData(c.width,c.height); window.draws=0; window.noise=setInterval(()=>{for(let i=0;i<img.data.length;i+=65536)crypto.getRandomValues(img.data.subarray(i,Math.min(i+65536,img.data.length)));for(let i=3;i<img.data.length;i+=4)img.data[i]=255;ctx.putImageData(img,0,0);window.draws++},100); return true; })()"
    assert cli("js_evaluate", "--port", port, "--expression", animation)["result"]
    time.sleep(7)
    assert (
        cli("js_evaluate", "--port", port, "--expression", "window.draws")["result"]
        >= 20
    )
    failed = cli(
        "page_record_stop", "--recording-id", recording["recording_id"], exit_code=1
    )
    assert failed["error_code"] == "recording_failed" and "10 MB" in failed["error"]
    assert not out.exists()

    # Step 3: Execute operation
    cli("page_goto", "--port", port, "--url", recording_page[1])
    restarted = cli(
        "page_record_start",
        "--port",
        port,
        "--out",
        tmp_path / "shareable.gif",
        "--fps",
        2,
    )
    saved = cli("page_record_stop", "--recording-id", restarted["recording_id"])
    assert saved["saved"] and saved["size_bytes"] <= 10_000_000


# Smoke test - can import without errors
def test_imports_work():
    """Verify all imports are valid"""
    assert page_record_start is not None
    assert page_record_stop is not None
