#!/usr/bin/env bash
# Point this repo at .githooks/ and install Cursor session hooks for MCP sync.
set -euo pipefail

PROJECT_PATH="$(dirname "$(dirname "$(realpath "$0")")")"

cd "${PROJECT_PATH}"
git config core.hooksPath .githooks
chmod +x .githooks/post-merge .githooks/post-checkout deploy/hooks/mcp-sync.sh deploy/install-cursor-hooks.sh
"${PROJECT_PATH}/deploy/install-cursor-hooks.sh"

echo "Git hooks installed (core.hooksPath=.githooks)."
echo "post-merge and post-checkout will run: ./deploy/mcp.sh cursor-sync --all-targets --if-changed --enable-agent"

