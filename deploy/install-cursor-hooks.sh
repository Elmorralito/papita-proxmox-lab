#!/usr/bin/env bash
# Install project Cursor hooks so MCP configs stay synced on every agent session.
set -euo pipefail

PROJECT_PATH="$(dirname "$(dirname "$(realpath "$0")")")"
HOOKS_SRC="${PROJECT_PATH}/deploy/hooks"
HOOKS_DST="${PROJECT_PATH}/.cursor"

mkdir -p "${HOOKS_DST}/hooks"
install -m 755 "${HOOKS_SRC}/mcp-sync.sh" "${HOOKS_DST}/hooks/mcp-sync.sh"
install -m 644 "${HOOKS_SRC}/hooks.json" "${HOOKS_DST}/hooks.json"

echo "Cursor hooks installed:"
echo "  ${HOOKS_DST}/hooks.json"
echo "  ${HOOKS_DST}/hooks/mcp-sync.sh"
echo "sessionStart → ./deploy/mcp.sh cursor-sync --all-targets --if-changed --enable-agent"
