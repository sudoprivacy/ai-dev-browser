"""Retain host resource counts, never process arguments or network addresses."""

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import psutil


def record_host_resources(folder, phase):
    snapshot = {"phase": phase, "at": datetime.now(timezone.utc).isoformat()}
    try:
        current = psutil.Process()
        memory = psutil.virtual_memory()
        snapshot.update(
            pythonRss=current.memory_info().rss,
            pythonThreads=current.num_threads(),
            hostAvailableMemory=memory.available,
            hostTotalMemory=memory.total,
            tcpStates=dict(
                Counter(
                    connection.status for connection in psutil.net_connections("tcp4")
                )
            ),
        )
        chrome = []
        for process in psutil.process_iter(
            ["name", "num_threads", "memory_info"], ad_value=None
        ):
            if "chrome" in (process.info["name"] or "").lower():
                chrome.append(process.info)
        snapshot.update(
            chromeProcessCount=len(chrome),
            chromeThreads=sum(value["num_threads"] or 0 for value in chrome),
            chromeRss=sum(
                value["memory_info"].rss for value in chrome if value["memory_info"]
            ),
        )
        if sys.platform == "linux":
            snapshot["cgroup"] = {
                name: path.read_text().strip()
                for name in (
                    "pids.current",
                    "pids.max",
                    "pids.events",
                    "memory.current",
                    "memory.max",
                    "memory.events",
                )
                if (path := Path("/sys/fs/cgroup") / name).is_file()
            }
    except (psutil.Error, OSError) as error:
        snapshot["auditUnavailable"] = type(error).__name__
    (folder / f"host-resources-{phase}.json").write_text(
        json.dumps(snapshot, indent=2), encoding="utf8"
    )
