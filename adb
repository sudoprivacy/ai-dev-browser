#!/usr/bin/env bash
# ai-dev-browser CLI — zero-dependency bootstrap for macOS/Linux.
#
# Usage:
#   ./adb <tool> [args]
#   ./adb --list
#   ./adb page-find --help
#
# On first run, installs uv (if needed) and sets up the environment.
# Requires: curl. Does NOT require Python pre-installed.

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

# Ensure uv is available (installs to ~/.local/bin, no sudo)
if ! command -v uv &>/dev/null; then
    echo "Installing uv (Python package manager)..." >&2
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

exec uv run --directory "$DIR" python -m ai_dev_browser "$@"
