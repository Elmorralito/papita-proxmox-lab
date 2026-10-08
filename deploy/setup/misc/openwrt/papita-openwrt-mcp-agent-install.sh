#!/usr/bin/env bash
# Install / inspect / remove the openwrt-mcp router agent on the OpenWrt gateway (openwrt-pi).
#
# Runs on the WORKSTATION. Uses the existing root admin key ONLY for installation; the MCP server itself
# uses a separate, restricted key (forced command, no pty, no forwarding) that this script installs.
#
#   papita-openwrt-mcp-agent-install.sh install   --host 100.78.68.87 --admin-key ~/.ssh/id_ed25519_NASGW
#   papita-openwrt-mcp-agent-install.sh status    --host ... --admin-key ...
#   papita-openwrt-mcp-agent-install.sh uninstall --host ... --admin-key ...
#
# This script never edits the firewall, network, Tailscale or SSH daemon configuration.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_PATH="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
AGENT_SRC="${PROJECT_PATH}/mcp/openwrt-mcp/router-agent"

log() { printf '[%s] %s\n' "${1}" "${2}" >&2; }
die() { log "ERROR" "$1"; exit 1; }

ACTION="${1:-}"
if [[ -n "${ACTION}" ]]; then shift; fi

HOST="${OPENWRT_HOST:-}"
ADMIN_KEY="${OPENWRT_ADMIN_KEY:-}"
AGENT_KEY="${OPENWRT_SSH_KEY_PATH:-${HOME}/.ssh/id_ed25519_openwrt_mcp}"
KNOWN_HOSTS="${OPENWRT_KNOWN_HOSTS_PATH:-${HOME}/.config/openwrt-mcp/known_hosts}"
APPROVER_PUB="${OPENWRT_APPROVER_PUBKEY_PATH:-${HOME}/.config/openwrt-mcp/approver.pub}"
ASSUME_YES=0

while [[ $# -gt 0 ]]; do
    case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --admin-key) ADMIN_KEY="$2"; shift 2 ;;
    --agent-key) AGENT_KEY="$2"; shift 2 ;;
    --known-hosts) KNOWN_HOSTS="$2"; shift 2 ;;
    --approver-pub) APPROVER_PUB="$2"; shift 2 ;;
    --yes) ASSUME_YES=1; shift ;;
    *) die "Unknown option: $1" ;;
    esac
done

[[ "${ACTION}" =~ ^(install|status|uninstall)$ ]] || die "Usage: $0 install|status|uninstall --host IP --admin-key PATH [--agent-key PATH] [--known-hosts PATH] [--approver-pub PATH] [--yes]"
[[ "${HOST}" =~ ^[0-9a-fA-F:.]+$ ]] || die "--host must be an IP literal"
[[ -f "${ADMIN_KEY}" ]] || die "--admin-key file not found: ${ADMIN_KEY}"
for tool in ssh ssh-keygen ssh-keyscan; do command -v "${tool}" >/dev/null || die "${tool} is required"; done

admin_ssh() {
    ssh -i "${ADMIN_KEY}" -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=10 \
        -o StrictHostKeyChecking=accept-new "root@${HOST}" "$@"
}

push_file() { # push_file LOCAL REMOTE MODE
    admin_ssh "cat > '$2.new' && chmod $3 '$2.new' && mv '$2.new' '$2'" <"$1"
}

preflight() {
    log "INFO" "Preflight on ${HOST} (read-only checks)..."
    # shellcheck disable=SC2016  # expansion must happen on the router
    admin_ssh 'for b in /usr/bin/ucode /usr/bin/usign /sbin/procd /sbin/fw4 /sbin/uci; do [ -x "$b" ] || { echo "missing $b"; exit 1; }; done
        ucode -e "import {sha256} from \"digest\"; import * as u from \"uci\"; import * as f from \"fs\";" >/dev/null 2>&1 || { echo "missing ucode modules: apk add ucode-mod-digest"; exit 1; }
        strings /usr/sbin/dropbear | grep -q "no-port-forwarding" || { echo "dropbear lacks authorized_keys restrictions"; exit 1; }
        strings /usr/sbin/dropbear | grep -q "command=" || { echo "dropbear lacks forced command support"; exit 1; }
        fw4 -q check || { echo "fw4 check fails on the current config; refusing to install"; exit 1; }
        echo ok' || die "Preflight failed (see message above)."
}

pin_host_key() {
    mkdir -p "$(dirname "${KNOWN_HOSTS}")"
    local scanned live
    scanned="$(ssh-keyscan -t ed25519 "${HOST}" 2>/dev/null | head -1)"
    [[ -n "${scanned}" ]] || die "ssh-keyscan returned nothing for ${HOST}"
    # Fingerprint of the key as served on the network vs. as stored on the router (authenticated channel).
    live="$(printf '%s\n' "${scanned}" | ssh-keygen -lf - | awk '{print $2}')"
    local stored
    stored="$(admin_ssh 'dropbearkey -y -f /etc/dropbear/dropbear_ed25519_host_key 2>/dev/null | grep -i fingerprint' | awk '{print $NF}' || true)"
    log "INFO" "Host key fingerprint on the wire: ${live}"
    log "INFO" "Host key fingerprint on router : ${stored:-unknown}"
    if [[ -n "${stored}" && "${stored}" != "${live}" ]]; then
        die "Host key mismatch between the network and the router; NOT pinning."
    fi
    printf '%s\n' "${scanned}" >"${KNOWN_HOSTS}"
    chmod 600 "${KNOWN_HOSTS}"
    log "INFO" "Pinned host key in ${KNOWN_HOSTS}"
}

do_install() {
    [[ -d "${AGENT_SRC}" ]] || die "Agent sources not found: ${AGENT_SRC}"
    [[ -f "${APPROVER_PUB}" ]] || die "Approver public key not found (${APPROVER_PUB}). Run: openwrt-mcp-approve keygen"
    preflight

    if [[ ! -f "${AGENT_KEY}" ]]; then
        log "INFO" "Generating dedicated agent key ${AGENT_KEY} (no passphrase; protected by forced command + file perms)."
        ssh-keygen -q -t ed25519 -N "" -C "openwrt-mcp-agent" -f "${AGENT_KEY}"
    fi
    local publine
    publine="$(cat "${AGENT_KEY}.pub")"
    local keyline="command=\"/usr/libexec/openwrt-mcp-agent\",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ${publine}"

    if [[ "${ASSUME_YES}" -ne 1 ]]; then
        read -r -p "Install openwrt-mcp agent + watchdog on ${HOST} (no firewall changes)? [y/N] " ans
        [[ "${ans}" =~ ^[Yy]$ ]] || die "Aborted."
    fi

    log "INFO" "Installing agent, watchdog and approver public key..."
    admin_ssh 'mkdir -p /etc/openwrt-mcp /etc/openwrt-mcp/journal /etc/openwrt-mcp/used /usr/libexec && chmod 700 /etc/openwrt-mcp'
    push_file "${AGENT_SRC}/openwrt-mcp-agent.uc" /usr/libexec/openwrt-mcp-agent 755
    push_file "${AGENT_SRC}/openwrt-mcp-watchdog" /usr/libexec/openwrt-mcp-watchdog 755
    push_file "${AGENT_SRC}/openwrt-mcp-watchdog.init" /etc/init.d/openwrt-mcp-watchdog 755
    push_file "${APPROVER_PUB}" /etc/openwrt-mcp/approver.pub 644
    admin_ssh '/etc/init.d/openwrt-mcp-watchdog enable && /etc/init.d/openwrt-mcp-watchdog restart'

    log "INFO" "Installing restricted key (forced command) in /etc/dropbear/authorized_keys..."
    printf '%s\n' "${keyline}" | admin_ssh 'cat > /tmp/owrt-mcp.keyline && touch /etc/dropbear/authorized_keys &&
        { grep -qxF -f /tmp/owrt-mcp.keyline /etc/dropbear/authorized_keys || cat /tmp/owrt-mcp.keyline >> /etc/dropbear/authorized_keys; } &&
        chmod 600 /etc/dropbear/authorized_keys && rm -f /tmp/owrt-mcp.keyline'

    pin_host_key

    log "INFO" "Verifying with the restricted key (inspect)..."
    local out
    out="$(printf '{"v":1,"op":"inspect"}' | ssh -i "${AGENT_KEY}" -o BatchMode=yes -o IdentitiesOnly=yes \
        -o StrictHostKeyChecking=yes -o UserKnownHostsFile="${KNOWN_HOSTS}" -o GlobalKnownHostsFile=/dev/null \
        "root@${HOST}")" || die "Restricted-key inspect failed."
    echo "${out}"
    log "INFO" "Forced-command check: a plain shell request must NOT run a shell..."
    if ssh -i "${AGENT_KEY}" -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes \
        -o UserKnownHostsFile="${KNOWN_HOSTS}" -o GlobalKnownHostsFile=/dev/null "root@${HOST}" 'id' </dev/null 2>/dev/null | grep -q '^uid='; then
        admin_ssh 'sed -i "/openwrt-mcp-agent/d" /etc/dropbear/authorized_keys'
        die "SECURITY: restricted key executed an arbitrary command. The key line was removed."
    fi
    log "INFO" "Done. Set OPENWRT_SSH_KEY_PATH=${AGENT_KEY} OPENWRT_KNOWN_HOSTS_PATH=${KNOWN_HOSTS}, then run: ./deploy/mcp.sh smoke --server openwrt"
}

do_status() {
    admin_ssh 'ls -l /usr/libexec/openwrt-mcp-agent /usr/libexec/openwrt-mcp-watchdog /etc/openwrt-mcp 2>&1;
        echo "--- watchdog heartbeat (uptime) / now:"; cat /var/run/openwrt-mcp/watchdog.alive 2>&1; cut -d" " -f1 /proc/uptime;
        echo "--- active journal:"; cat /etc/openwrt-mcp/journal/active.json 2>&1 || true;
        echo "--- authorized_keys (agent line):"; grep openwrt-mcp-agent /etc/dropbear/authorized_keys | cut -c1-120 || true'
}

do_uninstall() {
    if [[ "${ASSUME_YES}" -ne 1 ]]; then
        read -r -p "Remove openwrt-mcp agent, watchdog and restricted key from ${HOST}? [y/N] " ans
        [[ "${ans}" =~ ^[Yy]$ ]] || die "Aborted."
    fi
    admin_ssh '[ -f /etc/openwrt-mcp/journal/active.json ] && { echo "active transaction present; resolve it first"; exit 1; } || true
        /etc/init.d/openwrt-mcp-watchdog stop 2>/dev/null; /etc/init.d/openwrt-mcp-watchdog disable 2>/dev/null
        sed -i "/openwrt-mcp-agent/d" /etc/dropbear/authorized_keys
        rm -f /usr/libexec/openwrt-mcp-agent /usr/libexec/openwrt-mcp-watchdog /etc/init.d/openwrt-mcp-watchdog
        echo removed (journal/backups kept in /etc/openwrt-mcp)'
}

case "${ACTION}" in
install) do_install ;;
status) do_status ;;
uninstall) do_uninstall ;;
esac
