"""Real Grok pool checkpoint/recovery acceptance using existing account cookies.

Install grok-web-connector and this checkout in the test environment, then run:
    python scripts/live_grok_pool_persistence.py --output scratch/grok-pool

Only reads favorites. Missing authentication and failed jobs fail the run.
Account results and copied cookies are removed after inspection; the report
contains counts and exception locations. Each run owns two unique profiles.
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path
import secrets
import shutil
import time
import traceback
from typing import Any

from ai_dev_browser.core import is_port_in_use
from grok_web import reap_orphan_chrome
from grok_web.auth import load_cookies
from grok_web.pool import BrowserWorkerPool, load_state

logging.disable(logging.CRITICAL)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument(
    "--config", type=Path, help="Grok cookie config; defaults to ~/.grok-config.json"
)
args = parser.parse_args()
prefix = "adb-pool-live-" + secrets.token_hex(8)
output = args.output.resolve() / prefix
output.mkdir(parents=True)
profiles_root = (Path.home() / ".grok-web-connector/profiles").resolve()
profiles = [(profiles_root / f"{prefix}-w{i}").resolve() for i in range(2)]
assert all(p.parent == profiles_root and not p.exists() for p in profiles)
state_file = output / "state.json"
config_file = output / "cookies.json"
report: dict[str, Any] = {
    "status": "failed",
    "scope": "Real Grok BrowserWorkerPool with the Python browser backend",
    "operation": "read favorites, save pending/completed jobs, reopen and recover",
    "rounds": [],
}
ports = set()
started = time.monotonic()


async def main():
    cookies = load_cookies(args.config)
    original_ids = []
    pending_id = None
    for round_index in range(2):
        report["stage"] = f"connect_round_{round_index + 1}"
        pool = BrowserWorkerPool(
            num_workers=2,
            state_file=state_file,
            max_retries=1,
            cookies=cookies,
            config_path=config_file,
            headless=True,
            close_chrome=True,
            profile_prefix=prefix,
        )
        try:
            await asyncio.wait_for(pool.__aenter__(), 100)
            round_ports = [w.port for w in pool._workers.values()]
            assert len(set(round_ports)) == 2, "Workers shared a Chrome port"
            ports.update(round_ports)
            print("Two real Grok workers connected, round", round_index + 1, flush=True)
            report["stage"] = f"read_round_{round_index + 1}"
            if round_index == 0:
                original_ids = [
                    await pool.run(
                        "list_posts", limit=1, source="favorites", _hold=True
                    )
                    for _ in range(2)
                ]
                results = await pool.wait(original_ids, timeout=90)
                assert len(results) == 2 and all(r.success for r in results.values()), (
                    "Grok list job failed"
                )
                assert {r.worker_id for r in results.values()} == {0, 1}, (
                    "Both workers must execute a job"
                )
                posts = [post for result in results.values() for post in result.data]
                assert any(isinstance(post.get("created_at"), str) for post in posts), (
                    "The account needs a favorite with a timestamp to exercise typed persistence"
                )
                pending_id = await pool.run(
                    "list_posts", limit=1, source="favorites", _hold=True
                )
                pool.save_state()
                report["rounds"].append(
                    {
                        "workers": 2,
                        "successful_reads": len(results),
                        "row_counts": [len(r.data) for r in results.values()],
                        "pending_before_shutdown": 1,
                    }
                )
            else:
                assert all(pool.get_result(i) is not None for i in original_ids), (
                    "Completed results lost"
                )
                result = (await pool.wait([pending_id], timeout=90))[pending_id]
                assert result.success, "Recovered job failed"
                assert sum(w.stats.success for w in pool._workers.values()) == 1, (
                    "Completed work replayed"
                )
                report["rounds"].append(
                    {
                        "workers": 2,
                        "successful_recovered_reads": 1,
                        "completed_results_retained": 2,
                    }
                )
        finally:
            await asyncio.wait_for(pool.__aexit__(None, None, None), 25)
        await asyncio.sleep(1)
        assert all(not is_port_in_use(port=p) for p in ports), (
            "Chrome remained after pool exit"
        )
    saved = load_state(state_file)
    assert len(saved.completed) == 3 and not saved.pending and not saved.in_progress
    report.update(status="passed", final_completed_jobs=3, ports_closed=True)


try:
    asyncio.run(main())
except BaseException as error:
    report["error_type"] = type(error).__name__
    report["error_frames"] = [
        {"file": Path(f.filename).name, "line": f.lineno, "function": f.name}
        for f in traceback.extract_tb(error.__traceback__)
    ]
    if isinstance(error, TypeError) and str(error).startswith("Object of type "):
        report["error"] = str(error)
    cause = error
    report["error_chain"] = []
    while cause is not None:
        report["error_chain"].append(
            {
                "type": type(cause).__name__,
                "errno": getattr(cause, "errno", None),
                "winerror": getattr(cause, "winerror", None),
                "frames": [
                    {
                        "file": Path(f.filename).name,
                        "line": f.lineno,
                        "function": f.name,
                    }
                    for f in traceback.extract_tb(cause.__traceback__)
                ],
            }
        )
        cause = cause.__cause__
    # Avoid printing responses or account details from an upstream exception.
finally:
    report["elapsed_seconds"] = round(time.monotonic() - started, 1)
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for profile in profiles:
        assert profile.parent == profiles_root and profile.name.startswith(
            prefix + "-w"
        )
        reap_orphan_chrome(user_data_dir=profile)
        for attempt in range(40):
            try:
                if profile.exists():
                    shutil.rmtree(profile)
                break
            except PermissionError:
                time.sleep(0.5)
        else:
            report.setdefault("cleanup_pending", []).append(str(profile))
    for path in (state_file, config_file):
        if path.exists():
            path.unlink()
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    print("Report:", output / "report.json", flush=True)
raise SystemExit(
    0 if report["status"] == "passed" and not report.get("cleanup_pending") else 1
)
