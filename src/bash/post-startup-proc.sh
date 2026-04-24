#!/bin/bash

set -euo pipefail

# Post-startup hook (systemd oneshot): clear Ceph maintenance from pre-shutdown, and on
# the designated main node optionally wake peer Proxmox nodes via WoL.

# -----------------------------------------------------------------------------
# Ceph: clear noout (paired with pre-shutdown-proc.sh "ceph osd set noout")
# -----------------------------------------------------------------------------
set_noout_flag() {
    if ! command -v ceph >/dev/null 2>&1; then
        echo "INFO: ceph not installed; skipping ceph osd unset noout."
        return 0
    fi
    echo "INFO: Unsetting Ceph OSD noout..."
    if ceph osd unset noout; then
        echo "INFO: Ceph OSD noout unset."
    else
        echo "WARN: Failed to unset Ceph OSD noout (cluster down, quorum loss, or no Ceph); continuing."
    fi
    return 0
}

# -----------------------------------------------------------------------------
# Wake-on-LAN: only on the node named in /etc/default/pve-main-node (step 7.2)
# -----------------------------------------------------------------------------
_current_host_matches_label() {
    local label=$1
    [[ -z "$label" ]] && return 1
    local h_builtin h_host h_short h_long
    h_builtin=${HOSTNAME:-}
    h_host=$(hostname 2>/dev/null || true)
    h_short=$(hostname -s 2>/dev/null || true)
    h_long=$(hostname -f 2>/dev/null || true)
    [[ "$label" == "$h_builtin" || "$label" == "$h_host" || "$label" == "$h_short" || "$label" == "$h_long" ]]
}

wake_on_lan_nodes() {
    if [[ ! -f /etc/default/pve-main-node ]]; then
        echo "INFO: Skipping Wake-on-LAN: /etc/default/pve-main-node not found."
        return 0
    fi
    local designated
    designated=$(sed 's/^[[:space:]]*//;s/[[:space:]]*$//' /etc/default/pve-main-node)
    if [[ -z "$designated" ]]; then
        echo "INFO: Skipping Wake-on-LAN: /etc/default/pve-main-node is empty."
        return 0
    fi
    if ! _current_host_matches_label "$designated"; then
        echo "INFO: Skipping Wake-on-LAN: this host is not the main node (${designated})."
        return 0
    fi
    if ! command -v jq >/dev/null 2>&1 || ! command -v pvesh >/dev/null 2>&1 || ! command -v pvenode >/dev/null 2>&1; then
        echo "WARN: jq, pvesh, or pvenode not found; skipping Wake-on-LAN."
        return 0
    fi

    echo "INFO: Waking cluster nodes via Wake-on-LAN (main node)..."
    local json_out
    if ! json_out=$(pvesh get /cluster/resources --type node --output-format json 2>/dev/null); then
        echo "WARN: pvesh failed to list nodes; skipping Wake-on-LAN."
        return 0
    fi

    local node
    while IFS= read -r node; do
        [[ -z "$node" ]] && continue
        if _current_host_matches_label "$node"; then
            echo "INFO: Skipping WoL for ${node} (this host)."
            continue
        fi
        echo "INFO: Sending WoL to ${node}..."
        if ! pvenode wakeonlan "$node"; then
            echo "WARN: pvenode wakeonlan failed for ${node}; continuing."
        fi
    done < <(jq -r '.[] | .node // empty' <<<"$json_out" 2>/dev/null || true)

    echo "INFO: Wake-on-LAN pass complete."
    return 0
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
main() {
    set_noout_flag
    wake_on_lan_nodes
    return 0
}

main "$@"
