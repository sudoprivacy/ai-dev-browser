#!/usr/bin/env python3
"""Sync CDP protocol module from cdp-python submodule.

Usage:
    python scripts/sync_cdp.py

After updating the submodule:
    git submodule update --remote vendor/cdp-python
    python scripts/sync_cdp.py
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "vendor" / "cdp-python" / "cdp"
DST = ROOT / "ai_dev_browser" / "cdp"


def main():
    if not SRC.exists():
        print(f"ERROR: Source not found: {SRC}")
        print("Run: git submodule update --init vendor/cdp-python")
        raise SystemExit(1)

    # Remove old cdp/ (except __pycache__)
    if DST.exists():
        shutil.rmtree(DST)

    # Copy fresh
    shutil.copytree(SRC, DST, ignore=shutil.ignore_patterns("__pycache__"))

    count = len(list(DST.glob("*.py")))
    print(f"Synced {count} CDP modules from {SRC} → {DST}")


if __name__ == "__main__":
    main()
