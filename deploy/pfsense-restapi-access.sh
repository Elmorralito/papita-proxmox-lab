#!/usr/bin/env bash
# Bootstrap pfREST access: clear Allowed Interfaces (Tailscale is not selectable in WebGUI).
# shellcheck disable=SC1090,SC1091
set -euo pipefail

PROJECT_PATH="$(dirname "$(dirname "$(realpath "$0")")")"
CURSOR_MCP_JSON="${CURSOR_MCP_JSON:-${HOME}/.cursor/mcp.json}"
ACTION="${1:-fix-access}"
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
    if [[ -f "${PROJECT_PATH}/.env" ]]; then
        log INFO "Loading Tailscale Admin API vars from ${PROJECT_PATH}/.env (if present)"
        set -a
        # shellcheck source=/dev/null
        source "${PROJECT_PATH}/.env"
        set +a
    fi
    if [[ -z "${PFSENSE_API_KEY:-}" ]]; then
        log ERROR "PFSENSE_API_KEY is not set. Run ./deploy/mcp.sh cursor-sync and edit ~/.cursor/mcp.json"
        exit 1
    fi
}

_ensure_bootstrap_cli() {
    if [[ ! -x "${PROJECT_PATH}/.venv/bin/pfsense-mcp-bootstrap" ]]; then
        log INFO "Installing pfsense-mcp console scripts..."
        poetry run pip install -e "${PROJECT_PATH}/mcp/pfsense-mcp" --no-deps --force-reinstall --no-cache-dir
    fi
}

action_fix_access() {
    _load_pfsense_env
    _ensure_bootstrap_cli
    cd "${PROJECT_PATH}"

    log INFO "Clearing pfREST allowed_interfaces (empty = all interfaces, incl. Tailscale)..."
    if ! poetry run pfsense-mcp-bootstrap allow-all-interfaces; then
        log ERROR "PATCH failed (see errors above)."
        log INFO "If you are logged into pfSense WebGUI, use the manual steps below."
        action_webgui_steps
        exit 1
    fi

    log INFO "Probing API on configured host ${PFSENSE_HOST:-?}..."
    if poetry run pfsense-mcp-bootstrap probe-version; then
        log INFO "pfREST reachable on ${PFSENSE_HOST:-configured host}."
    else
        log WARN "Probe on ${PFSENSE_HOST:-host} failed; check TLS (PFSENSE_VERIFY_SSL) or Access Lists."
    fi

    log INFO "Running MCP smoke test..."
    ./deploy/mcp.sh smoke --server pfsense-mcp
}

action_show_settings() {
    _load_pfsense_env
    _ensure_bootstrap_cli
    cd "${PROJECT_PATH}"
    poetry run pfsense-mcp-bootstrap show-restapi-settings --json
}

action_webgui_steps() {
    cat <<EOF
Manual fallback (pfSense WebGUI):
  System → REST API → Settings → Allowed Interfaces → deselect ALL → Save

Tailscale is not listed there (package-managed interface group). An empty selection
matches pfREST PATCH {"allowed_interfaces": []} — API accepts calls on any interface.

Then restrict with System → REST API → Access Lists and firewall rules.
EOF
}

case "${ACTION}" in
fix-access)
    action_fix_access
    ;;
show-settings)
    action_show_settings
    ;;
webgui-steps)
    action_webgui_steps
    ;;
-h | --help | help)
    usage_pfsense_restapi_access 0
    ;;
*)
    log ERROR "Unknown action: ${ACTION}"
    usage_pfsense_restapi_access
    ;;
esac

log INFO "Done."
