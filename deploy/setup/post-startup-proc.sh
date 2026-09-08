#!/bin/bash

set -euo pipefail

PAPITA_POST_STARTUP_DEFAULTS="/etc/default/papita-post-startup"
QUORUM_WAIT_SEC=120
PVECM_STATUS_TIMEOUT=10
CEPH_COMMAND_TIMEOUT=30
WOL_COMMAND_TIMEOUT=60
# Step 10.4: single-node recovery. A lone node of a 3+ node cluster can never be
# quorate on its own, so pmxcfs stays read-only and "onboot: 1" guests cannot
# start. Opt in to lower expected votes when every peer is verified
# unreachable, then start the guests listed below.
FORCE_QUORUM_IF_ISOLATED=0
FORCE_QUORUM_GUESTS=""
PEER_PING_TIMEOUT=2
GUEST_COMMAND_TIMEOUT=120

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
_load_post_startup_defaults() {
    if [[ -f "$PAPITA_POST_STARTUP_DEFAULTS" ]]; then
        # shellcheck disable=SC1090
        source "$PAPITA_POST_STARTUP_DEFAULTS"
    fi
    return 0
}

_is_quorate() {
    timeout "${PVECM_STATUS_TIMEOUT}" pvecm status 2>/dev/null | grep -qE 'Quorate:[[:space:]]+Yes'
}

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

# Emit "name=ring0_addr" per configured corosync node. /etc/pve stays readable
# (read-only) without quorum; the local copy is the fallback if pmxcfs is not up.
_corosync_nodes() {
    local conf path
    for path in /etc/pve/corosync.conf /etc/corosync/corosync.conf; do
        if [[ -r "$path" ]]; then
            conf="$path"
            break
        fi
    done
    [[ -z "${conf:-}" ]] && return 1
    awk '
        /^[[:space:]]*node[[:space:]]*\{/ { name = ""; addr = ""; next }
        /^[[:space:]]*name:/              { name = $2; next }
        /^[[:space:]]*ring0_addr:/        { addr = $2; next }
        /^[[:space:]]*\}/                 {
            if (name != "" && addr != "") { print name "=" addr }
            name = ""; addr = ""
        }
    ' "$conf"
}

# -----------------------------------------------------------------------------
# Ceph: clear noout (paired with pre-shutdown-proc.sh "ceph osd set noout")
# -----------------------------------------------------------------------------
set_noout_flag() {
    if ! command -v ceph >/dev/null 2>&1; then
        echo "INFO: ceph not installed; skipping ceph osd unset noout."
        return 0
    fi
    echo "INFO: Unsetting Ceph OSD noout..."
    if timeout "${CEPH_COMMAND_TIMEOUT}" ceph osd unset noout; then
        echo "INFO: Ceph OSD noout unset."
    else
        echo "WARN: Failed to unset Ceph OSD noout (cluster down, quorum loss, timeout, or no Ceph); continuing."
    fi
    return 0
}

# -----------------------------------------------------------------------------
# Wait for Proxmox cluster quorum before Ceph maintenance changes (optional)
# -----------------------------------------------------------------------------
wait_for_pve_quorum() {
    if ! command -v pvecm >/dev/null 2>&1; then
        echo "INFO: pvecm not found; skipping quorum wait."
        return 0
    fi
    local elapsed=0
    local interval=5
    echo "INFO: Waiting up to ${QUORUM_WAIT_SEC}s for Proxmox cluster quorum..."
    while ((elapsed < QUORUM_WAIT_SEC)); do
        if _is_quorate; then
            echo "INFO: Cluster is quorate."
            return 0
        fi
        sleep "$interval"
        elapsed=$((elapsed + interval))
    done
    echo "WARN: Timed out waiting for quorum after ${QUORUM_WAIT_SEC}s; continuing."
    return 1
}

# -----------------------------------------------------------------------------
# Isolated node: lower expected votes only when no peer answers, then start the
# configured guests (PVE will not do it itself once pve-guests has already run).
# -----------------------------------------------------------------------------
force_quorum_if_isolated() {
    if [[ "${FORCE_QUORUM_IF_ISOLATED}" != "1" ]]; then
        echo "INFO: FORCE_QUORUM_IF_ISOLATED not enabled; leaving expected votes untouched."
        return 1
    fi
    if ! command -v pvecm >/dev/null 2>&1; then
        echo "WARN: pvecm not found; cannot lower expected votes."
        return 1
    fi

    local nodes entry name addr
    if ! nodes=$(_corosync_nodes) || [[ -z "$nodes" ]]; then
        echo "WARN: Could not read the corosync nodelist; refusing to lower expected votes."
        return 1
    fi

    local -a peers=() reachable=()
    while IFS= read -r entry; do
        [[ -z "$entry" ]] && continue
        name=${entry%%=*}
        addr=${entry#*=}
        _current_host_matches_label "$name" && continue
        peers+=("${name}=${addr}")
    done <<<"$nodes"

    if ((${#peers[@]} == 0)); then
        echo "WARN: No corosync peers found; refusing to lower expected votes."
        return 1
    fi

    for entry in "${peers[@]}"; do
        name=${entry%%=*}
        addr=${entry#*=}
        if ping -c 1 -W "${PEER_PING_TIMEOUT}" "$addr" >/dev/null 2>&1; then
            echo "WARN: Peer ${name} (${addr}) answers but the cluster is not quorate."
            reachable+=("$name")
        else
            echo "INFO: Peer ${name} (${addr}) is unreachable."
        fi
    done

    # A reachable peer means corosync is partitioned rather than the node being
    # alone; lowering votes on both sides of a partition splits /etc/pve.
    if ((${#reachable[@]} > 0)); then
        echo "ERROR: Refusing to lower expected votes: peer(s) reachable (${reachable[*]}). Resolve the corosync partition instead."
        return 1
    fi

    echo "INFO: All ${#peers[@]} peer(s) unreachable; lowering expected votes to 1 (runtime only, resets on reboot or when peers rejoin)."
    if ! timeout "${PVECM_STATUS_TIMEOUT}" pvecm expected 1; then
        echo "WARN: 'pvecm expected 1' failed; /etc/pve stays read-only."
        return 1
    fi
    if ! _is_quorate; then
        echo "WARN: Still not quorate after lowering expected votes."
        return 1
    fi
    echo "INFO: Node is quorate on a single vote."
    return 0
}

_guest_command() {
    local vmid=$1
    if timeout "${PVECM_STATUS_TIMEOUT}" qm config "$vmid" >/dev/null 2>&1; then
        echo "qm"
        return 0
    fi
    if timeout "${PVECM_STATUS_TIMEOUT}" pct config "$vmid" >/dev/null 2>&1; then
        echo "pct"
        return 0
    fi
    return 1
}

start_isolated_guests() {
    if [[ -z "${FORCE_QUORUM_GUESTS//[[:space:],]/}" ]]; then
        echo "INFO: FORCE_QUORUM_GUESTS is empty; no guests to start."
        return 0
    fi

    local -a guests=()
    IFS=', ' read -r -a guests <<<"${FORCE_QUORUM_GUESTS}"

    local vmid cli status
    for vmid in "${guests[@]}"; do
        [[ -z "$vmid" ]] && continue
        if [[ ! "$vmid" =~ ^[0-9]+$ ]]; then
            echo "WARN: Ignoring invalid guest id '${vmid}'."
            continue
        fi
        if ! cli=$(_guest_command "$vmid"); then
            echo "WARN: Guest ${vmid} not found on this node; skipping."
            continue
        fi
        status=$(timeout "${PVECM_STATUS_TIMEOUT}" "$cli" status "$vmid" 2>/dev/null || true)
        if [[ "$status" == *running* ]]; then
            echo "INFO: Guest ${vmid} already running."
            continue
        fi
        echo "INFO: Starting guest ${vmid} via ${cli}..."
        if timeout "${GUEST_COMMAND_TIMEOUT}" "$cli" start "$vmid"; then
            echo "INFO: Guest ${vmid} started."
        else
            echo "WARN: Failed to start guest ${vmid}; continuing."
        fi
    done
    return 0
}

# -----------------------------------------------------------------------------
# Wake-on-LAN: only on the node named in /etc/default/pve-main-node (step 10.2)
# -----------------------------------------------------------------------------
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
        if ! timeout "${WOL_COMMAND_TIMEOUT}" pvenode wakeonlan "$node"; then
            echo "WARN: pvenode wakeonlan failed or timed out for ${node}; continuing."
        fi
    done < <(jq -r '.[] | .node // empty' <<<"$json_out" 2>/dev/null || true)

    echo "INFO: Wake-on-LAN pass complete."
    return 0
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
main() {
    _load_post_startup_defaults
    if ! wait_for_pve_quorum; then
        if force_quorum_if_isolated; then
            start_isolated_guests
        fi
    fi
    set_noout_flag
    wake_on_lan_nodes
    return 0
}

main "$@"
