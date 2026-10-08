"""Paid live CLI steering acceptance: real model choices, real browser, real GIF.

The text-only model sees installed tool names and core help. The runner executes
its choices only in an isolated fixture. Credentials are inherited, never saved.
"""

import argparse
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ai_dev_browser import core
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.tools._generate import _discover_tools

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.integration.recording_demo_support import decode, make_page

SYSTEM = """Choose the next browser CLI call for the user's task. You are a text-only
test subject. Use no built-in tools, network, shell or files. Reply with exactly one
JSON object: {"tool":"name","args":["--flag","value"]}, {"help":"name"}, or
{"done":true,"summary":"outcome"}. A runner executes the call and supplies --port.
Use the actual installed tool listing and help, and rely on returned completion
state. Do not invent parameters or repeat completed actions."""
ALLOWED = {
    "page_record_start",
    "page_record_stop",
    "page_screenshot",
    "page_discover",
    "click_by_html_id",
    "click_by_ref",
    "click_by_text",
    "type_by_text",
    "type_by_ref",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--scenario", choices=["default", "recovery", "both"], default="both"
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = shutil.which("claude")
    assert executable, "Claude CLI is required; live model acceptance did not run"
    functions = [tool["name"] for tool in _discover_tools()]
    catalog = "\n".join(
        f"{name}: {inspect.getdoc(getattr(core, name)).split('Args:')[0]}"
        for name in sorted(functions)
    )
    report = {"status": "failed", "scenarios": [], "model_requests": 0}
    env = dict(
        os.environ,
        AI_DEV_BROWSER_RECORDING_DIR=str(output / "recordings"),
        PYTHONUTF8="1",
    )
    result = browser_start(headless=True, temp=True, reuse="none", silent_stderr=True)
    assert "error" not in result, result
    port = result["port"]

    def call(tool, flags, supply_port=True):
        command = [sys.executable, "-m", f"ai_dev_browser.tools.{tool}"]
        if supply_port and tool != "page_record_stop":
            command += ["--port", str(port)]
        run = subprocess.run(
            command + flags,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
        if run.stdout.strip():
            payload = json.loads(run.stdout)
        else:
            assert run.returncode != 0, "CLI succeeded without its JSON result"
            payload = {"cli_error": run.stderr.strip()}
        print(f"actual {tool}: exit={run.returncode}", flush=True)
        return {"exit_code": run.returncode, "result": payload}

    try:
        with tempfile.TemporaryDirectory(prefix="adb-recording-model-") as context:
            for name, recover in (
                ("discover default demo", False),
                ("recover output conflict", True),
            ):
                if args.scenario != "both" and recover != (args.scenario == "recovery"):
                    continue
                folder = output / ("recovery" if recover else "default")
                folder.mkdir()
                first, _ = make_page(folder)
                assert call("page_goto", ["--url", first])["exit_code"] == 0
                destination = folder / "model.gif"
                history = []
                if recover:
                    conflict = folder / "existing.gif"
                    conflict.write_bytes(b"preserve existing file")
                    failed = call("page_record_start", ["--out", str(conflict)])
                    assert (
                        failed["exit_code"] == 5
                        and failed["result"]["retryable"] is False
                    )
                    history.append(
                        {
                            "tool": "page_record_start",
                            "args": ["--out", str(conflict)],
                            **failed,
                        }
                    )
                task = (
                    f"Create a GIF for a human viewer at {destination}. The browser is on a local form. "
                    "Start recording, click the known HTML id open, fill the field labeled Request name "
                    "with Model demo, then finish and save the recording. Leave the form open. "
                    "Use the normal recording defaults and report completion from the saved result."
                )
                entry = {"name": name, "turns": [], "calls": []}
                report["scenarios"].append(entry)
                started = None
                saved = None
                failures = 0
                for _ in range(12):
                    prompt = (
                        SYSTEM
                        + "\nInstalled tools/help:\n"
                        + catalog
                        + "\nTask:\n"
                        + task
                        + "\nHistory:\n"
                        + json.dumps(history)
                    )
                    request = subprocess.run(
                        [
                            executable,
                            "--print",
                            "--safe-mode",
                            "--no-session-persistence",
                            "--tools",
                            "",
                            "--system-prompt",
                            SYSTEM,
                            "--output-format",
                            "json",
                            "--max-budget-usd",
                            "2",
                        ],
                        cwd=context,
                        env=env,
                        input=prompt,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        timeout=120,
                        check=False,
                    )
                    report["model_requests"] += 1
                    assert request.returncode == 0, (
                        f"Model request failed: {request.stderr[:1000]}"
                    )
                    response = json.loads(request.stdout)
                    assert not response.get("is_error") and not response.get(
                        "tool_uses"
                    ), response.get("result")
                    text = response["result"].strip()
                    if text.startswith("```"):
                        text = "\n".join(text.splitlines()[1:-1])
                    try:
                        choice = json.loads(text)
                    except json.JSONDecodeError as exc:
                        entry["invalid_response"] = text
                        raise AssertionError(
                            "Model did not return a JSON choice"
                        ) from exc
                    entry["turns"].append(
                        {
                            "choice": choice,
                            "models": list(response.get("modelUsage", {})),
                            "usage": response.get("usage"),
                        }
                    )
                    print(f"model choice: {json.dumps(choice)}", flush=True)
                    if choice.get("done"):
                        assert saved and started, (
                            "Model declared completion before saving"
                        )
                        assert saved["demo"] and Path(saved["path"]).is_file()
                        actual = call(
                            "js_evaluate",
                            ["--expression", "document.querySelector('#name').value"],
                        )
                        assert actual["result"]["result"] == "Model demo", actual
                        decode(saved, folder)
                        entry["status"] = "passed"
                        if recover:
                            assert conflict.read_bytes() == b"preserve existing file"
                        break
                    tool = choice.get("tool") or choice.get("help")
                    assert tool in ALLOWED, choice
                    if "help" in choice:
                        help_text = subprocess.check_output(
                            [
                                sys.executable,
                                "-m",
                                f"ai_dev_browser.tools.{tool}",
                                "--help",
                            ],
                            text=True,
                            encoding="utf-8",
                        )
                        history.append({"help": tool, "result": help_text})
                        continue
                    flags = choice["args"]
                    assert isinstance(flags, list) and all(
                        isinstance(flag, str) for flag in flags
                    )
                    assert not any(
                        flag.split("=")[0]
                        in {
                            "--port",
                            "--tab-url",
                            "--transport",
                            "--profile",
                            "--no-demo",
                        }
                        for flag in flags
                    ), choice
                    if not entry["calls"]:
                        assert tool == "page_record_start", choice
                    actual = call(tool, flags)
                    entry["calls"].append(tool)
                    assert len(entry["calls"]) <= 8, (
                        "Unnecessary calls or repeated actions"
                    )
                    history.append({**choice, **actual})
                    if actual["exit_code"] != 0:
                        failures += 1
                        assert failures <= 2, actual
                        continue
                    if tool == "page_record_start":
                        assert started is None
                        started = actual["result"]
                        entry["recording_id"] = started["recording_id"]
                    if tool == "page_record_stop":
                        saved = actual["result"]
                else:
                    raise AssertionError("Model did not finish")
                assert entry["calls"][-1] == "page_record_stop", entry
                entry["saved"] = saved
        report["status"] = "passed"
    finally:
        # The recorder is detached; finalize any owned active fixture before
        # stopping its browser, including when model acceptance fails.
        for entry in report["scenarios"]:
            if "recording_id" in entry:
                call(
                    "page_record_stop",
                    ["--recording-id", entry["recording_id"]],
                    supply_port=False,
                )
        browser_stop(port=port)
        (output / "model-steering.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {"status": report["status"], "model_requests": report["model_requests"]}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
