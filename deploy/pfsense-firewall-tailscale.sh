#!/usr/bin/env bash
# Apply agreed Tailscale-tab firewall rules on pfSense via pfREST.
# shellcheck disable=SC1090,SC1091
set -euo pipefail

PROJECT_PATH="$(dirname "$(dirname "$(realpath "$0")")")"
CURSOR_MCP_JSON="${CURSOR_MCP_JSON:-${HOME}/.cursor/mcp.json}"
ACTION="${1:-apply}"
shift || true

# shellcheck source=${PROJECT_PATH}/deploy/utils.sh
{
    cd "${PROJECT_PATH}" && source "${PROJECT_PATH}/deploy/utils.sh"
} || {
    echo "[ERROR] Runtime - cannot load utils path."
    exit 255
}

# shellcheck source=${PROJECT_PATH}/deploy/usage.sh
source "${PROJECT_PATH}/deploy/usage.sh"

_load_pfsense_env() {
    if [[ -f "${CURSOR_MCP_JSON}" ]] && jq -e '.mcpServers.pfsense.env' "${CURSOR_MCP_JSON}" >/dev/null 2>&1; then
        log INFO "Loading pfSense env from ${CURSOR_MCP_JSON}"
        # shellcheck disable=SC1090
        eval "$(jq -r '.mcpServers.pfsense.env | to_entries[] | "export \(.key)=\(.value|@sh)"' "${CURSOR_MCP_JSON}")"
    fi
    if [[ -z "${PFSENSE_API_KEY:-}" ]]; then
        log ERROR "PFSENSE_API_KEY is not set. Run ./deploy/mcp.sh cursor-sync and edit ~/.cursor/mcp.json"
        exit 1
    fi
}

_ensure_firewall_cli() {
    if [[ ! -x "${PROJECT_PATH}/.venv/bin/pfsense-mcp-firewall" ]]; then
        log INFO "Installing pfsense-mcp console scripts..."
        poetry run pip install -e "${PROJECT_PATH}/mcp/pfsense-mcp" --no-deps --force-reinstall --no-cache-dir
    fi
}

action_apply() {
    local extra_args=()
    while [[ "$#" -gt 0 ]]; do
        case "$1" in
        --dry-run)
            extra_args+=(--dry-run)
            shift
            ;;
        --skip-smoke)
            extra_args+=(--skip-smoke)
            shift
            ;;
        --json)
            extra_args+=(--json)
            shift
            ;;
        *)
            log ERROR "Unknown option: $1"
            usage_pfsense_firewall_tailscale
            ;;
        esac
    done
    _load_pfsense_env
    _ensure_firewall_cli
    cd "${PROJECT_PATH}"
    poetry run pfsense-mcp-firewall ${extra_args+"${extra_args[@]}"}
}

case "${ACTION}" in
apply)
    action_apply "$@"
    ;;
-h | --help | help)
    usage_pfsense_firewall_tailscale 0
    ;;
*)
    log ERROR "Unknown action: ${ACTION}"
    usage_pfsense_firewall_tailscale
    ;;
esac

log INFO "Done."
