#!/usr/bin/env bash
# Sync mcp/*/mcp.json.example → ~/.cursor/mcp.json and .cursor/mcp.json on session start.
set -euo pipefail

PROJECT_PATH="$(dirname "$(dirname "$(realpath "$0")")")"
[[ -f "${PROJECT_PATH}/deploy/mcp.sh" ]] || exit 0

cd "${PROJECT_PATH}"
./deploy/mcp.sh cursor-sync --all-targets --if-changed --enable-agent 2>/dev/null || true
exit 0
