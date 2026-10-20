"""Bound fixture cleanup and retain the phase, task and thread diagnostics."""

import asyncio
from datetime import datetime, timezone
from io import StringIO
import json
import sys
import traceback


def record_phase(folder, phase, **details):
    path = folder / "extension-cleanup-evidence.json"
    history = json.loads(path.read_text()) if path.exists() else []
    history.append(
        {"phase": phase, "time": datetime.now(timezone.utc).isoformat(), **details}
    )
    path.write_text(json.dumps(history, indent=2), encoding="utf-8")


def record_stacks(folder):
    output = StringIO()
    for task in asyncio.all_tasks():
        task.print_stack(file=output)
    for identity, frame in sys._current_frames().items():
        output.write(f"\nThread {identity}\n")
        output.writelines(traceback.format_stack(frame))
    (folder / "extension-cleanup-stacks.txt").write_text(
        output.getvalue(), encoding="utf-8"
    )


async def close_live_server(server, folder, timeout=15):
    record_phase(folder, "bridge-close-start")
    server.close()
    try:
        await asyncio.wait_for(server.wait_closed(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        record_phase(folder, "bridge-close-timeout", timeout=timeout)
        record_stacks(folder)
        raise AssertionError(
            f"Live bridge cleanup exceeded {timeout}s; see extension-cleanup-stacks.txt"
        ) from exc
    record_phase(folder, "bridge-closed")


async def close_live_extension(chrome, server, folder, timeout=30):
    from ai_dev_browser.core.browser import browser_stop

    try:
        # Let the still-running extension acknowledge WebSocket close frames.
        # Killing Chrome first resets its sockets on Windows and leaves the
        # legacy server waiting for a peer that can no longer finish closing.
        await close_live_server(server, folder)
    finally:
        if chrome and "port" in chrome:
            record_phase(folder, "chrome-stop-start", pid=chrome["pid"])
            try:
                # Preserve verified PID ownership even when lsof isn't installed.
                result = await asyncio.wait_for(
                    asyncio.to_thread(browser_stop, session_id=chrome["session_id"]),
                    timeout=timeout,
                )
            except asyncio.TimeoutError as exc:
                record_phase(folder, "chrome-stop-timeout", timeout=timeout)
                record_stacks(folder)
                raise AssertionError(
                    f"Owned Chrome cleanup exceeded {timeout}s"
                ) from exc
            record_phase(folder, "chrome-stopped", result=result)
            assert result.get("stopped") and result.get("count") == 1, result
