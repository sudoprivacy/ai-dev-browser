"""Real CLI recovery: fix bad inputs while preserving one browser and one submit."""

from pathlib import Path


def steering_recovery_journey(lifecycle):
    cli = lifecycle.cli
    for tool, expected in (
        ("browser_start", "isolated automation"),
        ("browser_connect", "real Chrome/profile"),
        ("cookies_import", "device-bound identity"),
        ("page_record_start", "viewer-friendly GIF"),
        ("tab_switch", "--tab-url"),
    ):
        help_text = " ".join(cli(tool, "--help").split())
        assert expected in help_text, (tool, expected)
    assert '"accept" to OK/submit' in cli("dialog_respond", "--help")

    started = lifecycle.start("--headless", "True", "--temp", "--silent-stderr")
    identity = started["session_id"]
    scope = ("--session-id", identity)
    lifecycle.page(identity)
    lifecycle.approve(identity)

    invalid = cli("storage_set", *scope, exit_code=2)
    assert invalid["error_code"] == "validation" and invalid["retryable"] is False
    assert "JSON object" in invalid["hint"] and "key and value" in invalid["hint"]
    written = cli(
        "storage_set",
        *scope,
        "--items",
        '{"draft":"one request","quoted":"a \\"quote\\""}',
    )
    assert written == {"set": 2, "verified": True}
    paired = cli("storage_set", *scope, "--key", "draft", "--value", "one request")
    assert paired == {"key": "draft", "value": "one request", "verified": True}
    stored = cli("storage_get", *scope, "--key", "draft")
    assert stored == {"key": "draft", "value": "one request"}

    missing = lifecycle.root / "does-not-exist.dat"
    failed_load = cli("cookies_load", *scope, "--path", missing, exit_code=4)
    assert failed_load["error_code"] == "not_found"
    assert failed_load["retryable"] is False and "cookies_save" in failed_load["hint"]
    saved = cli("cookies_save", *scope, "--path", lifecycle.root / "session.dat")
    assert saved["saved"] and Path(saved["path"]).stat().st_size > 0
    assert cli("cookies_load", *scope, "--path", saved["path"])["loaded"]

    stale = cli("html_by_ref", *scope, "--ref", "0#2147483647", exit_code=4)
    assert stale["error_code"] == "not_found" and stale["retryable"] is False
    assert "page_discover" in stale["hint"]
    elements = cli("page_discover", *scope)
    button = next(
        element for element in elements if element.get("name") == "Submit request"
    )
    html = cli("html_by_ref", *scope, "--ref", button["ref"])
    assert 'id="submit"' in html["html"]

    waited = cli(
        "page_wait_url",
        *scope,
        "--exact",
        lifecycle.server.url + "/never",
        "--timeout",
        "0.1",
    )
    assert waited["matched"] is False and waited["retryable"] is False
    assert "blind replay" in waited["hint"]
    assert lifecycle.server.approvals == [{"trusted": True}]
    assert lifecycle.server.submissions == []

    lifecycle.submit(identity, stored["value"])
    info = cli("page_info", *scope)
    assert info["url"] == lifecycle.server.url + "/login"
    assert len(lifecycle.server.approvals) == len(lifecycle.server.submissions) == 1
    assert lifecycle.server.submissions[0]["name"] == stored["value"]
    assert lifecycle.server.submissions[0]["trusted"] is True
    screenshot = cli(
        "page_screenshot", *scope, "--path", lifecycle.root / "accepted.png"
    )
    assert Path(screenshot["path"]).stat().st_size > 0
    cli.evidence(
        "steering-recovery",
        approvals=lifecycle.server.approvals,
        submissions=lifecycle.server.submissions,
    )


async def extension_storage_journey(extension, folder):
    """Compare core and fresh CLI storage results in a real extension-owned page."""
    import asyncio
    import json
    import os
    import sys

    from ai_dev_browser.core import page_goto, storage_get, storage_set
    from tests.integration.browser_lifecycle_support import LifecycleServer

    server = LifecycleServer()
    history = []
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("AI_DEV_BROWSER_")
    }
    environment["AI_DEV_BROWSER_EXTENSION_BRIDGE_PORT"] = str(extension.port)
    environment["PYTHONUTF8"] = "1"

    async def invoke(tool, *flags):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            f"ai_dev_browser.tools.{tool}",
            "--transport",
            "extension",
            "--tab-url",
            server.url,
            *flags,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        assert process.returncode == 0, (stdout, stderr)
        result = json.loads(stdout)
        history.append({"tool": tool, "result": result})
        return result

    try:
        await extension.call(page_goto, url=server.url + "/login")
        value = 'A "quoted" value with unicode 中文'
        written = await extension.call(storage_set, items={"draft": value})
        assert written == {"set": 1, "verified": True}
        direct = await extension.call(storage_get, key="draft")
        assert direct == {"key": "draft", "value": value}
        assert await invoke("storage_get", "--key", "draft") == direct
        changed = await invoke(
            "storage_set", "--key", "draft", "--value", value + " updated"
        )
        assert changed == {
            "key": "draft",
            "value": value + " updated",
            "verified": True,
        }
        await extension.call(page_goto, url=server.url + "/login")
        persisted = await extension.call(storage_get, key="draft")
        assert persisted == {"key": "draft", "value": changed["value"]}
        assert server.approvals == server.submissions == []
        (folder / "extension-storage-evidence.json").write_text(
            json.dumps({"history": history, "persisted": persisted}), encoding="utf-8"
        )
    finally:
        server.close()
