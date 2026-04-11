#!/usr/bin/env bash
# shellcheck disable=SC1090,SC1091
set -euo pipefail

ENV=
TARGET_USERNAME="root"
TARGET_REMOTE_PATH="/${TARGET_USERNAME}"
PROJECT_PATH="$(dirname "$(dirname "$(realpath "$0")")")"

# shellcheck source=${PROJECT_PATH}/deploy/utils.sh
{
    cd "${PROJECT_PATH}" && source "${PROJECT_PATH}/deploy/utils.sh"
} || {
    echo "[ERROR] Runtime - cannot load utils path."
    exit 255
}

# shellcheck source=${PROJECT_PATH}/deploy/usage.sh
{
    cd "${PROJECT_PATH}" && source "${PROJECT_PATH}/deploy/usage.sh"
} || {
    echo "[ERROR] Runtime - cannot load usage path."
    exit 255
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --ip-address | -ip)
            IP_ADDRESS="$2"
            shift 2
            ;;
        --username | -user)
            TARGET_USERNAME="$2"
            shift 2
            ;;
        --target-path | -tp)
            TARGET_REMOTE_PATH="$2"
            shift 2
            ;;
        --help | -h)
            usage_proxmox
            shift 1
            ;;
        *)
            shift
            ;;
    esac
done

if [ -z "$IP_ADDRESS" ]; then
    log "ERROR" "No IP address was provided."
    usage_proxmox
fi

if [ -z "$TARGET_USERNAME" ]; then
    log "ERROR" "No username was provided."
    usage_proxmox
fi

# Unix domain socket paths must stay short (e.g. macOS ~104 chars). Avoid long TMPDIR
# (/var/folders/...) and cm-%r@%h:%p (OpenSSH may lengthen it further).
_ssh_mux_base="$(mktemp -u "/tmp/papita-pm.XXXXXX")"
SSH_MUX_SOCKET="${_ssh_mux_base}-%C"
# One authenticated session; scp and later ssh reuse it (single password prompt if needed).
SSH_COMMON_OPTS=(
    -o ControlMaster=auto
    -o "ControlPath=${SSH_MUX_SOCKET}"
    -o ControlPersist=120
)

_proxmox_ssh_cleanup() {
    ssh "${SSH_COMMON_OPTS[@]}" -O exit "${TARGET_USERNAME}@${IP_ADDRESS}" 2>/dev/null || true
}
trap _proxmox_ssh_cleanup EXIT

if ! ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" "true"; then
    log "ERROR" "Failed to connect to $IP_ADDRESS using username $TARGET_USERNAME."
    usage_proxmox
fi

log "INFO" "Connected to $IP_ADDRESS using username $TARGET_USERNAME (SSH multiplexing enabled)."

log "WARN" "Replacing ${TARGET_REMOTE_PATH}/deploy on $IP_ADDRESS (removing old copy before transfer)."
# Pass path as argv (not inside one remote "…" string) so SC2029 does not apply; path expands locally by design.
ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" rm -rf -- "${TARGET_REMOTE_PATH}/deploy"

log "INFO" "Deploying setup-pve-node bundle to $IP_ADDRESS:$TARGET_REMOTE_PATH/deploy."
scp "${SSH_COMMON_OPTS[@]}" -r "$PROJECT_PATH/src/bash" "$TARGET_USERNAME@$IP_ADDRESS:$TARGET_REMOTE_PATH/deploy"
scp "${SSH_COMMON_OPTS[@]}" "$PROJECT_PATH/deploy/utils.sh" "$TARGET_USERNAME@$IP_ADDRESS:$TARGET_REMOTE_PATH/deploy/utils.sh"
scp "${SSH_COMMON_OPTS[@]}" "$PROJECT_PATH/deploy/usage.sh" "$TARGET_USERNAME@$IP_ADDRESS:$TARGET_REMOTE_PATH/deploy/usage.sh"
scp "${SSH_COMMON_OPTS[@]}" "$PROJECT_PATH/deploy/setup-pve-node.usage.txt" "$TARGET_USERNAME@$IP_ADDRESS:$TARGET_REMOTE_PATH/deploy/setup-pve-node.usage.txt"

log "INFO" "Deployed src/bash/, utils.sh, usage.sh, and setup-pve-node.usage.txt to $IP_ADDRESS:$TARGET_REMOTE_PATH/deploy."

ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" chmod -R a+rx "${TARGET_REMOTE_PATH}/deploy"

log "INFO" "Set permissions for $IP_ADDRESS:$TARGET_REMOTE_PATH/deploy."

# -tt: allocate a remote PTY so setup-pve-node.sh prompts (read -e/-p) work even if stdin here is not a TTY.
# Remote TERM fallback when the client did not set one (e.g. some IDE terminals).
ssh "${SSH_COMMON_OPTS[@]}" -tt "$TARGET_USERNAME@$IP_ADDRESS" "cd ${TARGET_REMOTE_PATH}/deploy && export TERM=\${TERM:-xterm-256color} && exec bash setup-pve-node.sh"

log "INFO" "Done."
