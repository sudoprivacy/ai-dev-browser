"""Paid names/help discovery against real Chrome and an HTTP result ledger.

Uses an isolated Claude CLI context and inherited API credentials. No mocked
browser/model responses. A separate native desktop actor confirms the visible
scenario; existing Chrome uses a persistently installed, owned test profile.
"""

from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import psutil

from ai_dev_browser import core
from ai_dev_browser.tools._generate import _discover_tools

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.live_recording_steering import parse_choice
from tests.integration.browser_lifecycle_support import LifecycleCLI, LifecycleServer


SYSTEM = """Choose the next browser CLI call for the user. Reply with one JSON object:
{"tool":"name","args":["--flag","value"]}, {"help":"name"}, or
{"done":true,"summary":"actual outcome or missing setup"}.
Use the installed tool listing and actual help. Do not use built-in tools, shell,
files, plugins or other network access. Rely on actual returned state. Do not
repeat completed side effects. A test runner executes your selected CLI call."""
ALLOWED = {
    "browser_start",
    "browser_connect",
    "browser_reconnect",
    "browser_disconnect",
    "page_goto",
    "page_info",
    "page_html",
    "browser_list",
    "page_discover",
    "page_wait_element",
    "page_screenshot",
    "click_by_text",
    "click_by_html_id",
    "click_by_ref",
    "type_by_text",
    "type_by_ref",
    "find_by_text",
    "find_by_html_id",
    "js_evaluate",
    "tab_list",
}


def native_confirmation(pid):
    """A second desktop UI client acts in the same visible Chrome page."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.integration.browser_lifecycle_ui",
            "--confirm-pid",
            str(pid),
        ],
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scenario",
        choices=["background", "visible", "existing", "unsupported", "all"],
        default="all",
    )
    parser.add_argument("--prepared-profile", type=Path)
    parser.add_argument("--bridge-port", type=int, default=9577)
    parser.add_argument(
        "--chrome-path",
        default=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = shutil.which("claude") or str(Path.home() / ".local/bin/claude.exe")
    assert Path(executable).is_file(), "A real Claude CLI/API is required"
    catalog = "\n".join(
        f"{tool['name']}: {inspect.getdoc(getattr(core, tool['name'])).splitlines()[0]}"
        for tool in _discover_tools()
    )
    report = {
        "status": "failed",
        "catalog": "installed names and first lines",
        "cases": [],
        "model_requests": 0,
    }
    selected = (
        ["background", "visible", "existing", "unsupported"]
        if args.scenario == "all"
        else [args.scenario]
    )
    try:
        for scenario in selected:
            folder = output / scenario
            folder.mkdir(exist_ok=True)
            server = LifecycleServer()
            cli = LifecycleCLI(folder, AI_DEV_BROWSER_CHROME=args.chrome_path)
            context = None
            playwright = None
            sessions = []
            known = None
            history = []
            entry = {
                "scenario": scenario,
                "status": "failed",
                "turns": [],
                "history": history,
            }
            report["cases"].append(entry)
            began = time.monotonic()
            try:
                if scenario == "existing":
                    from playwright.sync_api import sync_playwright

                    assert args.prepared_profile and args.prepared_profile.is_dir(), (
                        "Provide an owned test profile with the actual bridge persistently installed"
                    )
                    cli.env["AI_DEV_BROWSER_EXTENSION_BRIDGE_PORT"] = str(
                        args.bridge_port
                    )
                    playwright = sync_playwright().start()
                    context = playwright.chromium.launch_persistent_context(
                        str(args.prepared_profile.resolve()),
                        executable_path=args.chrome_path,
                        headless=True,
                        ignore_default_args=["--disable-extensions"],
                    )
                    page = context.pages[0]
                    page.goto(server.url + "/login")
                    page.wait_for_function(
                        "window.serverState && window.serverState.logged_in"
                    )
                    sentinel = context.new_page()
                    sentinel.goto(server.url + "/sentinel")
                    task = f"Use my already running, logged-in real Chrome/profile to open {server.url}/ and confirm then submit a request named Real profile. Keep my other tabs and Chrome running. A fresh isolated profile will not have my login."
                elif scenario == "unsupported":
                    task = f"Use the Chrome/profile at {folder / 'unconfigured'} with my existing real login to complete the form at {server.url}/. Keep it in the background with no window. If setup is unavailable, explain exactly what is needed and stop; do not substitute another profile or browser mode."
                elif scenario == "visible":
                    # Explicit user request must win over a configured background default.
                    cli.env["AI_DEV_BROWSER_HEADLESS"] = "true"
                    task = f"Open a new visible local browser window at {server.url}/login. I need to see and work on the same page. I will confirm as user, then you should enter Visible collaboration in Request name and submit once. Leave the result visible."
                else:
                    task = f"Complete the form at {server.url}/login in a new isolated background browser with no visible window. Confirm as user, enter Background request in Request name, and submit once."
                entry["task"] = task
                with tempfile.TemporaryDirectory(
                    prefix="adb-lifecycle-model-"
                ) as isolated:
                    for _ in range(22):
                        prompt = (
                            SYSTEM
                            + "\nInstalled tools:\n"
                            + catalog
                            + "\nTask:\n"
                            + task
                            + "\nActual history:\n"
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
                            input=prompt,
                            capture_output=True,
                            encoding="utf-8",
                            env=cli.env,
                            cwd=isolated,
                            timeout=120,
                        )
                        report["model_requests"] += 1
                        response = json.loads(request.stdout)
                        assert request.returncode == 0 and not response.get(
                            "is_error"
                        ), response.get("result")
                        choice = parse_choice(response["result"])
                        entry["turns"].append(
                            {
                                "choice": choice,
                                "model_text": response["result"],
                                "models": list(response.get("modelUsage", {})),
                                "usage": response.get("usage"),
                            }
                        )
                        print("actual model choice", choice, flush=True)
                        if choice.get("done"):
                            if scenario == "unsupported":
                                assert (
                                    not sessions
                                    and not server.approvals
                                    and not server.submissions
                                )
                                assert any(
                                    h.get("result", {}).get("error_code")
                                    in ("unsupported", "validation", "transient")
                                    for h in history
                                )
                                assert choice.get("summary")
                            else:
                                assert (
                                    known
                                    and len(server.approvals)
                                    == len(server.submissions)
                                    == 1
                                )
                                expected_name = {
                                    "background": "Background request",
                                    "visible": "Visible collaboration",
                                    "existing": "Real profile",
                                }[scenario]
                                assert server.submissions == [
                                    {"trusted": True, "name": expected_name}
                                ], server.submissions
                                assert server.approvals == [{"trusted": True}]
                                if scenario in ("background", "visible"):
                                    assert known["transport"] == "cdp" and known[
                                        "headless"
                                    ] is (scenario == "background")
                                    actual = psutil.Process(known["pid"]).cmdline()
                                    assert any(
                                        a.startswith("--headless") for a in actual
                                    ) is (scenario == "background")
                                    entry["actual_launch_args"] = actual
                                else:
                                    assert (
                                        known["transport"] == "extension"
                                        and known["owner"] == "external"
                                    )
                                    assert (
                                        sentinel.url == server.url + "/sentinel"
                                        and not sentinel.is_closed()
                                    )
                                cli(
                                    "page_screenshot",
                                    "--session-id",
                                    known["session_id"],
                                    "--path",
                                    str(folder / "final-page.png"),
                                )
                            entry.update(
                                status="passed",
                                approvals=server.approvals,
                                submissions=server.submissions,
                                duration_seconds=round(time.monotonic() - began, 2),
                            )
                            break
                        tool = choice.get("tool") or choice.get("help")
                        assert tool in (
                            {t["name"] for t in _discover_tools()}
                            if "help" in choice
                            else ALLOWED
                        ), choice
                        if "help" in choice:
                            history.append({"help": tool, "text": cli(tool, "--help")})
                            continue
                        flags = list(choice.get("args", []))
                        if tool == "browser_connect" and scenario != "existing":
                            assert known, (
                                "Only the owned fixture session may be reattached"
                            )
                        if tool == "browser_start":
                            assert not sessions, "The model attempted a second launch"
                            if scenario == "unsupported":
                                assert "--user-data-dir" in flags and Path(
                                    flags[flags.index("--user-data-dir") + 1]
                                ).resolve() in (
                                    folder.resolve(),
                                    (folder / "unconfigured").resolve(),
                                )
                            else:
                                assert "--user-data-dir" not in flags, (
                                    "This task creates only an isolated fixture"
                                )
                        if tool.startswith(
                            ("page_", "click_", "type_", "find_")
                        ) or tool in ("js_evaluate", "tab_list"):
                            assert known, (
                                "No fixture browser connection was established"
                            )
                            # Supplied connection flags must identify this exact fixture.
                            if "--session-id" in flags:
                                assert (
                                    flags[flags.index("--session-id") + 1]
                                    == known["session_id"]
                                )
                            if "--port" in flags:
                                assert int(
                                    flags[flags.index("--port") + 1]
                                ) == known.get("port")
                        run = subprocess.run(
                            [
                                sys.executable,
                                "-m",
                                f"ai_dev_browser.tools.{tool}",
                                *flags,
                            ],
                            capture_output=True,
                            encoding="utf-8",
                            env=cli.env,
                            timeout=120,
                        )
                        payload = (
                            json.loads(run.stdout)
                            if run.stdout.strip()
                            else {
                                "error": run.stderr,
                                "error_code": "validation",
                                "retryable": False,
                            }
                        )
                        history.append(
                            {
                                "tool": tool,
                                "args": flags,
                                "exit_code": run.returncode,
                                "result": payload,
                            }
                        )
                        print(f"actual CLI {tool}: exit={run.returncode}", flush=True)
                        if tool in (
                            "browser_start",
                            "browser_connect",
                            "browser_reconnect",
                        ) and payload.get("connected"):
                            known = payload
                            cli.env["AI_DEV_BROWSER_SESSION_ID"] = known["session_id"]
                            if (
                                known.get("owner") == "adb"
                                and known["session_id"] not in sessions
                            ):
                                sessions.append(known["session_id"])
                        if (
                            scenario == "visible"
                            and tool in ("page_goto", "browser_start")
                            and run.returncode == 0
                            and not server.approvals
                            and payload.get("url", "").rstrip("/")
                            == (server.url + "/login")
                        ):
                            cli(
                                "page_wait_element",
                                "--session-id",
                                known["session_id"],
                                "--selector",
                                '#result[data-logged-in="true"][data-approved="0"]',
                            )
                            native_confirmation(known["pid"])
                            server.wait(lambda: len(server.approvals) == 1)
                            assert server.approvals == [{"trusted": True}]
                            history.append(
                                {
                                    "human": "Confirmed in the same visible Chrome page using independent desktop UI input; continue with the request name and submission"
                                }
                            )
                    else:
                        raise AssertionError(
                            "Model did not finish within the live request limit"
                        )
            finally:
                entry["server_outcome"] = {
                    "approvals": server.approvals,
                    "submissions": server.submissions,
                    "attempts": server.attempts,
                }
                entry["cli_calls"] = cli.history
                for session in reversed(sessions):
                    cli("browser_stop", "--session-id", session)
                if context:
                    cli("browser_disconnect")
                    context.close()
                if playwright:
                    playwright.stop()
                server.close()
        report["status"] = "passed"
    finally:
        (output / "model-steering.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "status": report["status"],
                "cases": len(report["cases"]),
                "model_requests": report["model_requests"],
            }
        )
    )


if __name__ == "__main__":
    main()
