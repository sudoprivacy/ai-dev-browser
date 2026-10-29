"""Real CLI receipts for a missing extension page; no user profile is touched."""

import asyncio

from tests.integration.browser_lifecycle_support import LifecycleCLI
from tests.integration.extension_ownership_support import wait_until, worker_call


async def closed_main_journey(extension, folder):
    cli = LifecycleCLI(folder, AI_DEV_BROWSER_EXTENSION_BRIDGE_PORT=str(extension.port))

    async def call(tool, *args, exit_code=0):
        return await asyncio.to_thread(cli, tool, *args, exit_code=exit_code)

    help_text = await call("browser_connect", "--help")
    assert all(
        word in help_text
        for word in ("bridge_connected", "page_available", "window_set")
    )
    initial = await call("browser_connect", "--transport", "extension")
    assert initial["connected"] and initial["tab_count"] == 1
    identity, main = initial["session_id"], initial["automation_target_id"]
    sentinel_id = await worker_call(
        extension,
        "chrome.tabs.create({url:'about:blank#unrelated-fixture',active:false}).then(t=>t.id)",
    )
    await worker_call(extension, f"chrome.tabs.remove({int(main)})")

    async def closed():
        return extension.bridge.identity.get("automation_target_id") is None

    await wait_until(closed, bool)
    missing = await call("browser_connect", "--transport", "extension", exit_code=4)
    assert (
        not missing["connected"]
        and missing["bridge_connected"]
        and not missing["page_available"]
    )
    assert (
        missing["error_code"] == "target_closed"
        and missing["tab_count"] == 0
        and not missing["retryable"]
    )
    assert missing["session_id"] == identity
    reconnect = await call("browser_reconnect", "--session-id", identity, exit_code=4)
    assert not reconnect["connected"] and not reconnect["reconnected"]
    assert reconnect["error_code"] == missing["error_code"]
    navigation = await call(
        "page_goto",
        "--session-id",
        identity,
        "--url",
        "https://example.invalid/never-send",
        exit_code=4,
    )
    assert navigation["error_code"] == "target_closed"
    remaining = await worker_call(
        extension,
        "chrome.tabs.query({}).then(tabs=>tabs.map(t=>({id:t.id,url:t.url})))",
    )
    assert remaining == [{"id": sentinel_id, "url": "about:blank#unrelated-fixture"}]
    cli.evidence(
        "extension-readiness",
        initial=initial,
        missing=missing,
        reconnect=reconnect,
        unrelated_target_preserved=sentinel_id,
    )
