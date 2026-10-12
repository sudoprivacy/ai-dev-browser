"""Causal assertions for generated real-browser lifecycle journeys."""

from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys

import psutil

from .browser_lifecycle_support import LifecycleCLI


class LifecycleJourneys:
    def __init__(self, root, server):
        self.root = Path(root)
        self.server = server
        self.cli = LifecycleCLI(root)
        self.sessions = []

    def cleanup(self):
        from ai_dev_browser.core import _session

        for identity in reversed(self.sessions):
            record = _session.read(identity)
            if _session.same_process(record):
                result = self.cli("browser_stop", "--session-id", identity)
                assert result["stopped"]
        # Failed starts intentionally leave Chrome running. This fixture owns
        # its isolated test profile; verify PID birth/executable before cleanup.
        for record in self.cli.launches:
            if _session.same_process(record):
                process = psutil.Process(record["pid"])
                children = process.children(recursive=True)
                for child in children:
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                process.terminate()
                psutil.wait_procs([process, *children], timeout=10)

    def start(self, *flags):
        result = self.cli("browser_start", *flags)
        assert result["connected"] and result["session_id"]
        self.sessions.append(result["session_id"])
        return result

    def page(self, identity, url=None):
        expected_url = url or self.server.url + "/login"
        if expected_url == self.server.url:
            expected_url += "/"
        result = self.cli(
            "page_goto",
            "--session-id",
            identity,
            "--url",
            expected_url,
        )
        assert result["success"] and result["url"] == expected_url
        self.cli(
            "page_wait_element", "--session-id", identity, "--selector", "#approve"
        )
        self.cli(
            "page_wait_element",
            "--session-id",
            identity,
            "--selector",
            '#result[data-logged-in="true"]',
        )

    def approve(self, identity):
        state = self.cli(
            "js_evaluate",
            "--session-id",
            identity,
            "--expression",
            "window.serverState",
        )["result"]
        assert state["logged_in"], state
        result = self.cli(
            "click_by_html_id", "--session-id", identity, "--html-id", "approve"
        )
        assert result["clicked"]
        self.cli(
            "js_evaluate",
            "--session-id",
            identity,
            "--expression",
            "({events:window.inputEvents,state:window.serverState,visibility:document.visibilityState,rect:document.querySelector('#approve').getBoundingClientRect().toJSON()})",
        )
        self.server.wait(lambda: len(self.server.approvals) == 1)
        assert self.server.approvals == [{"trusted": True}]

    def submit(self, identity, text):
        self.cli(
            "page_wait_element",
            "--session-id",
            identity,
            "--selector",
            '#result[data-approved="1"][data-logged-in="true"]',
        )
        state = self.cli(
            "js_evaluate",
            "--session-id",
            identity,
            "--expression",
            "window.serverState",
        )["result"]
        assert (
            state["logged_in"]
            and state["approvals"] == [{"trusted": True}]
            and state["submissions"] == []
        )
        typed = self.cli(
            "type_by_text",
            "--session-id",
            identity,
            "--name",
            "Request name",
            "--text",
            text,
        )
        assert typed["typed"] and typed["verified"]
        assert self.cli(
            "click_by_html_id", "--session-id", identity, "--html-id", "submit"
        )["clicked"]
        self.server.wait(lambda: len(self.server.submissions) == 1)
        assert self.server.submissions == [{"trusted": True, "name": text}]

    def owned_cdp(self):
        help_text = self.cli("browser_start", "--help")
        assert "device identity" in help_text and "cloud headful" in help_text
        started = self.start("--headless", "true", "--silent-stderr")
        identity = started["session_id"]
        pid = started["pid"]
        actual_args = psutil.Process(pid).cmdline()
        assert "--headless=new" in actual_args and started["headless"] is True
        assert started["owner"] == "adb" and started["capabilities"]["can_restart"]
        self.page(identity)
        self.approve(identity)
        self.cli(
            "tab_new", "--session-id", identity, "--url", self.server.url + "/sentinel"
        )
        disconnected = self.cli("browser_disconnect", "--session-id", identity)
        assert disconnected["disconnected"] and not disconnected["browser_closed"]
        reconnected = self.cli("browser_reconnect", "--session-id", identity)
        assert reconnected["reconnected"] and reconnected["session_id"] == identity
        assert reconnected["tab_count"] == 2
        assert (
            reconnected["pid"] == pid
            and reconnected["automation_target_id"] == started["automation_target_id"]
        )
        self.submit(identity, "After reconnect")
        restarted = self.cli("browser_restart", "--session-id", identity)
        assert restarted["restarted"] and restarted["previous_session_id"] == identity
        assert restarted["session_id"] != identity and restarted["pid"] != pid
        self.sessions.append(restarted["session_id"])
        assert not psutil.pid_exists(pid)
        stale = self.cli(
            "click_by_html_id",
            "--session-id",
            identity,
            "--html-id",
            "submit",
            exit_code=5,
        )
        assert stale["error_code"] == "session_changed" and not stale["retryable"]
        assert len(self.server.approvals) == len(self.server.submissions) == 1
        self.cli.evidence(
            "cdp-lifecycle",
            actual_launch_args=actual_args,
            approvals=self.server.approvals,
            submissions=self.server.submissions,
        )

    def installed_extension(self, configuration, headless):
        profile, binary, port, extension_id = configuration
        self.cli.env["AI_DEV_BROWSER_EXTENSION_BRIDGE_PORT"] = str(port)
        started = self.start(
            "--transport",
            "extension",
            "--user-data-dir",
            str(profile),
            "--chrome-path",
            binary,
            "--headless",
            str(headless).lower(),
        )
        identity = started["session_id"]
        pid = started["pid"]
        args = psutil.Process(pid).cmdline()
        assert all(
            not arg.startswith(
                ("--remote-debugging", "--load-extension", "--disable-extensions")
            )
            for arg in args
        )
        assert (
            f"--user-data-dir={profile}" in args
            and "--profile-directory=Default" in args
        )
        assert started["extension_id"] == extension_id
        assert started["owner"] == "adb" and started["profile_owner"] == "user"
        assert (
            started["headless"] is headless
            and any(arg.startswith("--headless") for arg in args) is headless
        )
        self.page(identity, self.server.url)
        self.approve(identity)
        busy = self.cli(
            "browser_start",
            "--transport",
            "extension",
            "--user-data-dir",
            str(profile),
            "--chrome-path",
            binary,
            "--headless",
            str(headless).lower(),
            exit_code=5,
        )
        assert busy["error_code"] == "conflict" and busy["running_pids"] == [pid]
        assert psutil.pid_exists(pid)
        disconnected = self.cli("browser_disconnect", "--session-id", identity)
        assert not disconnected["browser_closed"] and psutil.pid_exists(pid)
        recovered = self.cli(
            "browser_reconnect", "--session-id", identity, "--timeout", 15
        )
        assert (
            recovered["session_id"] == identity
            and recovered["profile_id"] == started["profile_id"]
        )
        assert (
            recovered["automation_target_id"] == started["automation_target_id"]
            and recovered["pid"] == pid
        )
        self.submit(identity, "Profile login preserved")
        shot = self.cli(
            "page_screenshot",
            "--session-id",
            identity,
            "--path",
            str(self.root / "extension-lifecycle.png"),
        )
        assert Path(shot["path"]).stat().st_size > 1000
        self.cli.evidence(
            "extension-lifecycle",
            actual_launch_args=args,
            approvals=self.server.approvals,
            submissions=self.server.submissions,
        )

    def existing_extension(self, configuration):
        from playwright.sync_api import sync_playwright
        from ai_dev_browser.core._session import profile_processes

        profile, binary, port, extension_id = configuration
        self.cli.env["AI_DEV_BROWSER_EXTENSION_BRIDGE_PORT"] = str(port)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(profile),
                executable_path=binary,
                headless=False,
                ignore_default_args=["--disable-extensions"],
            )
            try:
                sentinel = context.new_page()
                sentinel.goto(self.server.url + "/sentinel")
                process = profile_processes(profile)[0]
                pid = process["pid"]
                connected = self.cli(
                    "browser_connect", "--transport", "extension", "--timeout", 15
                )
                identity = connected["session_id"]
                assert (
                    connected["owner"] == "external"
                    and not connected["capabilities"]["can_close"]
                )
                assert profile_processes(profile)[0]["pid"] == pid
                self.page(identity, self.server.url)
                assert self.cli(
                    "js_evaluate",
                    "--session-id",
                    identity,
                    "--expression",
                    "window.serverState",
                )["result"]["logged_in"]
                self.cli(
                    "cdp_send",
                    "--session-id",
                    identity,
                    "--method",
                    "Target.activateTarget",
                    "--params",
                    json.dumps({"targetId": connected["automation_target_id"]}),
                )
                actor = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "tests.integration.browser_lifecycle_ui",
                        "--confirm-pid",
                        str(pid),
                    ],
                    env=self.cli.env,
                    capture_output=True,
                    encoding="utf-8",
                    timeout=30,
                )
                assert actor.returncode == 0, (actor.stdout, actor.stderr)
                self.server.wait(lambda: len(self.server.approvals) == 1)
                assert self.server.approvals == [{"trusted": True}]
                refused = self.cli(
                    "browser_restart", "--session-id", identity, exit_code=7
                )
                assert (
                    refused["error_code"] == "auth_failed"
                    and refused["affected_resources"] == []
                )
                assert profile_processes(profile)[0]["pid"] == pid
                unknown_stop = self.cli(
                    "browser_stop",
                    "--session-id",
                    identity,
                    "--allow-external",
                    exit_code=6,
                )
                assert unknown_stop["error_code"] == "unsupported"
                self.cli("browser_disconnect", "--session-id", identity)
                resumed = self.cli(
                    "browser_reconnect", "--session-id", identity, "--timeout", 15
                )
                assert (
                    resumed["session_id"] == identity
                    and resumed["automation_target_id"]
                    == connected["automation_target_id"]
                )
                self.submit(identity, "Same human page")
                self.cli("browser_disconnect", "--session-id", identity)
                assert sentinel.url == self.server.url + "/sentinel"
                assert sentinel.locator("h1").inner_text() == "Leave this tab untouched"
                assert profile_processes(profile)[0]["pid"] == pid
                self.cli.evidence(
                    "existing-extension",
                    existing_pid=pid,
                    sentinel_url=sentinel.url,
                    approvals=self.server.approvals,
                    submissions=self.server.submissions,
                )
                original = [p for p in context.pages if p.url == self.server.url + "/"]
                assert len(original) == 1
                original[
                    0
                ].close()  # The separate Chrome client closes the user's page.
                refused_page = self.cli(
                    "click_by_html_id",
                    "--session-id",
                    identity,
                    "--html-id",
                    "submit",
                    exit_code=4,
                )
                assert (
                    refused_page["error_code"] == "target_closed"
                    and refused_page["retryable"] is False
                )
                assert len(self.server.approvals) == len(self.server.submissions) == 1
                assert (
                    sentinel.url == self.server.url + "/sentinel"
                    and profile_processes(profile)[0]["pid"] == pid
                )
                self.cli.evidence(
                    "existing-extension",
                    existing_pid=pid,
                    sentinel_url=sentinel.url,
                    closed_target_refused=refused_page,
                    approvals=self.server.approvals,
                    submissions=self.server.submissions,
                )
            finally:
                context.close()

    def delayed_extension(self, configuration):
        profile, binary, port, _ = configuration
        self.cli.env["AI_DEV_BROWSER_EXTENSION_BRIDGE_PORT"] = str(port)
        delayed = self.cli(
            "browser_start",
            "--transport",
            "extension",
            "--user-data-dir",
            profile,
            "--chrome-path",
            binary,
            "--headless",
            "true",
            "--startup-timeout",
            0,
            exit_code=6,
        )
        assert delayed["started"] and delayed["owner"] == "adb"
        assert not delayed["browser_closed"] and psutil.pid_exists(delayed["pid"])
        connected = self.cli(
            "browser_connect", "--transport", "extension", "--timeout", 20
        )
        identity = connected["session_id"]
        self.sessions.append(identity)
        assert connected["owner"] == "adb" and connected["pid"] == delayed["pid"]
        assert connected["user_data_dir"] == str(profile)
        self.page(identity, self.server.url)
        self.approve(identity)
        self.submit(identity, "Late handshake preserved ownership")
        self.cli.evidence(
            "delayed-extension",
            approvals=self.server.approvals,
            submissions=self.server.submissions,
        )

    def unsupported(self):
        missing = self.cli(
            "browser_start",
            "--transport",
            "extension",
            "--user-data-dir",
            str(self.root / "unconfigured"),
            "--headless",
            "true",
            exit_code=6,
        )
        assert missing["error_code"] == "unsupported" and missing["retryable"] is False
        assert "installed and enabled" in missing["error"] and "pid" not in missing
        assert missing["setup_instructions"] and missing["hint"]
        legacy = self.cli(
            "browser_start",
            "--transport",
            "extension",
            "--user-data-dir",
            str(self.root / "unconfigured"),
            "--headless",
            "old",
            exit_code=6,
        )
        assert (
            legacy["error_code"] == "unsupported"
            and "legacy headless" in legacy["error"]
        )
        started = self.start("--headless", "true", "--silent-stderr")
        identity = started["session_id"]
        mode = self.cli(
            "browser_connect",
            "--session-id",
            identity,
            "--headless",
            "false",
            exit_code=6,
        )
        assert mode["error_code"] == "unsupported" and "cannot change" in mode["error"]
        assert "--headless=new" in psutil.Process(started["pid"]).cmdline()
        self.page(identity)
        self.approve(identity)
        self.submit(identity, "Explicit choice")
        self.cli.evidence(
            "unsupported-lifecycle",
            approvals=self.server.approvals,
            submissions=self.server.submissions,
        )

    async def worker_oauth(self, extension):
        import asyncio
        from ai_dev_browser.core import (
            cdp_send,
            click_by_html_id,
            js_evaluate,
            page_goto,
            tab_close,
            tab_list,
        )

        before = (await extension.call(cdp_send, method="AiDevBrowser.debugState"))[
            "result"
        ]
        assert before["profileId"] and before["sessionId"]
        navigation = await extension.call(page_goto, url=self.server.url + "/login")
        assert navigation["success"]
        await extension.call(page_goto, url=self.server.url + "/popup")
        assert (await extension.call(click_by_html_id, html_id="oauth"))["clicked"]
        deadline = asyncio.get_running_loop().time() + 10
        while True:
            targets = (await extension.call(tab_list))["tabs"]
            children = [
                target
                for target in targets
                if target["url"] == self.server.url + "/oauth"
            ]
            if children:
                break
            assert asyncio.get_running_loop().time() < deadline, targets
            await asyncio.sleep(0.05)
        await extension.restart_worker()
        recovered = (await extension.call(cdp_send, method="AiDevBrowser.debugState"))[
            "result"
        ]
        assert (
            recovered["sessionId"] == before["sessionId"]
            and recovered["profileId"] == before["profileId"]
        )
        assert (
            recovered["mainTabId"] == before["mainTabId"]
            and len(recovered["autoTabs"]) == 2
        )
        consent = await extension.call(
            click_by_html_id, html_id="consent", tab_url=self.server.url + "/oauth"
        )
        assert consent["clicked"]
        await asyncio.to_thread(
            self.server.wait, lambda: len(self.server.approvals) == 1
        )
        assert self.server.approvals == [{"trusted": True}]
        assert (await extension.call(tab_close, tab_id=children[0]["id"]))["closed"]
        state = (
            await extension.call(
                js_evaluate,
                expression="window.serverState",
                tab_url=self.server.url + "/popup",
            )
        )["result"]
        assert state["logged_in"] and state["approvals"] == [{"trusted": True}]
        after = (await extension.call(cdp_send, method="AiDevBrowser.debugState"))[
            "result"
        ]
        assert after["sessionId"] == before["sessionId"] and after["autoTabs"] == [
            before["mainTabId"]
        ]
        self.cli.evidence(
            "worker-oauth",
            before=before,
            recovered=recovered,
            after=after,
            approvals=self.server.approvals,
        )
