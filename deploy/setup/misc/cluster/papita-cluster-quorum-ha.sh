#!/bin/bash
# Cluster-wide QDevice registration, TrueNAS NFS storage, HA group, and verification.
# Run once from an online cluster member (main node). Requires papita-node-qdevice-client.sh on all nodes.
set -euo pipefail

SCRIPT_DIR="$(dirname "$(realpath "$0")")"
DEPLOY_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

_log() {
    printf '[%s] %s\n' "$1" "$2"
}

_load_lab_defaults() {
    local qhost_file="${SCRIPT_DIR}/default.qdevice.host"
    local nfs_env="${SCRIPT_DIR}/default.truenas.nfs.env"

    if [[ -f "$qhost_file" ]]; then
        QDEVICE_HOST="$(list_file_active_lines "$qhost_file" 2>/dev/null | head -n1 || true)"
    fi
    QDEVICE_HOST="${QDEVICE_HOST:-${PAPITA_QDEVICE_HOST:-}}"

    if [[ -f "$nfs_env" ]]; then
        # shellcheck disable=SC1090
        source "$nfs_env"
    fi

    TRUENAS_NFS_SERVER="${TRUENAS_NFS_SERVER:-172.16.0.100}"
    TRUENAS_NFS_EXPORT="${TRUENAS_NFS_EXPORT:-/mnt/main/pve}"
    PVE_NFS_STORAGE_ID="${PVE_NFS_STORAGE_ID:-truenas-nfs}"
    PVE_NFS_CONTENT="${PVE_NFS_CONTENT:-images,rootdir,vzdump}"
    PVE_NFS_OPTIONS="${PVE_NFS_OPTIONS:-vers=4.1,hard,nconnect=4}"
    PVE_NFS_SHARE_TABLE="${PVE_NFS_SHARE_TABLE:-}"
    HA_GROUP_NAME="${HA_GROUP_NAME:-papita-ha}"
    HA_NODES="${HA_NODES:-}"
    HA_AUTO_ENROLL_NFS_GUESTS="${HA_AUTO_ENROLL_NFS_GUESTS:-0}"
}

# list_file_active_lines from deploy/utils.sh when sourced from proxmox remote path.
if [[ -f "${DEPLOY_ROOT}/utils.sh" ]]; then
    # shellcheck disable=SC1091
    source "${DEPLOY_ROOT}/utils.sh"
elif [[ -f "${SCRIPT_DIR}/../../utils.sh" ]]; then
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/../../utils.sh"
else
    list_file_active_lines() {
        grep -vE '^[[:space:]]*(#|$)' "$1" 2>/dev/null || true
    }
fi

_require_cluster_member() {
    if ! command -v pvecm >/dev/null 2>&1; then
        _log ERROR "pvecm not found; run on a Proxmox VE cluster member."
        exit 1
    fi
    local pvecm_out=""
    pvecm_out="$(pvecm status 2>&1)" || true
    if ! grep -qE 'Cluster information' <<<"$pvecm_out"; then
        _log ERROR "This host does not appear to be in a Proxmox cluster."
        exit 1
    fi
}

_ensure_cluster_firewall_nfs() {
    local cluster_fw="/etc/pve/firewall/cluster.fw"
    local nfs_rule="IN ACCEPT -source ${TRUENAS_NFS_SERVER} -log nolog"
    local lan_rule="IN ACCEPT -source 172.16.0.0/16 -log nolog"

    if [[ ! -d /etc/pve/firewall ]]; then
        _log WARN "No /etc/pve/firewall; skipping NFS firewall rule."
        return 0
    fi

    if [[ ! -f "$cluster_fw" ]]; then
        _log INFO "Creating minimal ${cluster_fw} with LAN + TrueNAS rules."
        cat <<EOF >"$cluster_fw"
[OPTIONS]
enable: 0
policy_out: ACCEPT

[RULES]
${lan_rule}
${nfs_rule}
OUT ACCEPT -log nolog
EOF
        return 0
    fi

    if grep -qF "${TRUENAS_NFS_SERVER}" "$cluster_fw"; then
        _log INFO "Cluster firewall already references ${TRUENAS_NFS_SERVER}."
        return 0
    fi

    awk -v rule="${nfs_rule}" '/^\[RULES\]$/ { print; print rule; next } 1' "$cluster_fw" >"${cluster_fw}.tmp"
    mv "${cluster_fw}.tmp" "$cluster_fw"
    _log INFO "Added cluster firewall rule: accept IN from TrueNAS ${TRUENAS_NFS_SERVER}."
}

_nfs_share_rows() {
    local line
    if [[ -n "${PVE_NFS_SHARE_TABLE:-}" ]]; then
        while IFS= read -r line || [[ -n "$line" ]]; do
            line="${line#"${line%%[![:space:]]*}"}"
            line="${line%"${line##*[![:space:]]}"}"
            [[ -z "$line" || "$line" == \#* ]] && continue
            printf '%s\n' "$line"
        done <<<"$PVE_NFS_SHARE_TABLE"
        return 0
    fi
    printf '%s|%s|%s\n' "$PVE_NFS_STORAGE_ID" "$TRUENAS_NFS_EXPORT" "$PVE_NFS_CONTENT"
}

_ensure_one_nfs_storage() {
    local storage_id="$1"
    local export_path="$2"
    local content="$3"

    if pvesm status -storage "$storage_id" &>/dev/null; then
        _log INFO "NFS storage '${storage_id}' already configured."
        return 0
    fi

    _log INFO "Adding NFS storage '${storage_id}' ${TRUENAS_NFS_SERVER}:${export_path} (${content})..."
    pvesm add nfs "$storage_id" \
        --server "$TRUENAS_NFS_SERVER" \
        --export "$export_path" \
        --content "$content" \
        --options "$PVE_NFS_OPTIONS"
    _log INFO "Added NFS storage '${storage_id}'."
}

_ensure_nfs_storage() {
    if ! command -v pvesm >/dev/null 2>&1; then
        _log ERROR "pvesm not found."
        exit 1
    fi

    if ! ping -c1 -W2 "$TRUENAS_NFS_SERVER" >/dev/null 2>&1; then
        _log WARN "Cannot ping ${TRUENAS_NFS_SERVER}; continuing (NFS may still work)."
    fi

    local line storage_id export_path content
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        IFS='|' read -r storage_id export_path content <<<"$line"
        storage_id="${storage_id//[[:space:]]/}"
        export_path="${export_path#"${export_path%%[![:space:]]*}"}"
        export_path="${export_path%"${export_path##*[![:space:]]}"}"
        content="${content#"${content%%[![:space:]]*}"}"
        content="${content%"${content##*[![:space:]]}"}"
        if [[ -z "$storage_id" || -z "$export_path" || -z "$content" ]]; then
            _log WARN "Skipping malformed NFS share row: ${line}"
            continue
        fi
        _ensure_one_nfs_storage "$storage_id" "$export_path" "$content"
    done < <(_nfs_share_rows)
}

_ensure_qdevice() {
    if [[ -z "$QDEVICE_HOST" ]]; then
        _log WARN "QDEVICE_HOST empty. Set misc/cluster/default.qdevice.host or PAPITA_QDEVICE_HOST. Skipping qdevice setup."
        return 0
    fi

    if pvecm status 2>/dev/null | grep -qi 'Qdevice'; then
        _log INFO "QDevice already configured in cluster."
        return 0
    fi

    if ! ping -c1 -W3 "$QDEVICE_HOST" >/dev/null 2>&1; then
        _log WARN "QDevice host ${QDEVICE_HOST} is unreachable. Skipping pvecm qdevice setup."
        _log WARN "Bring up a dedicated corosync-qnetd host (not TrueNAS, not a PVE node), then re-run setup-cluster-ha."
        return 0
    fi

    _log INFO "Registering QDevice at ${QDEVICE_HOST} (requires corosync-qdevice on all PVE nodes)..."
    if pvecm qdevice setup "$QDEVICE_HOST"; then
        _log INFO "QDevice setup completed."
        return 0
    fi
    _log WARN "pvecm qdevice setup failed for ${QDEVICE_HOST}; NFS/HA prep continues."
    return 0
}

_ha_nodes_csv() {
    if [[ -n "${HA_NODES:-}" ]]; then
        printf '%s' "$HA_NODES"
        return 0
    fi
    pvecm nodes 2>/dev/null | awk '/^[[:space:]]+[0-9]+/ { gsub(/\(local\)/, "", $3); print $3 }' | paste -sd, -
}

# PVE 9 node-affinity expects node:priority pairs.
_ha_nodes_priority_csv() {
    local csv node out=""
    csv="$(_ha_nodes_csv)"
    IFS=',' read -ra parts <<<"$csv"
    for node in "${parts[@]}"; do
        node="${node//[[:space:]]/}"
        [[ -z "$node" ]] && continue
        if [[ "$node" != *:* ]]; then
            node="${node}:1"
        fi
        out="${out:+$out,}$node"
    done
    printf '%s' "$out"
}

_ha_resource_ids_csv() {
    local resources_cfg="/etc/pve/ha/resources.cfg"
    if [[ ! -f "$resources_cfg" ]]; then
        return 0
    fi
    awk '
        /^vm: / { gsub(/^vm: /, "vm:"); print }
        /^ct: / { gsub(/^ct: /, "ct:"); print }
    ' "$resources_cfg" | paste -sd, -
}

_guest_disk_storage_ids() {
    local vmid="$1"
    local guest_type="$2"
    local cfg=""
    if [[ "$guest_type" == "qemu" ]]; then
        cfg="$(qm config "$vmid" 2>/dev/null || true)"
    else
        cfg="$(pct config "$vmid" 2>/dev/null || true)"
    fi
    if [[ -z "$cfg" ]]; then
        return 0
    fi
    grep -Eo '^[^:]+: [^:,]+' <<<"$cfg" | awk -F': ' '{print $2}' | cut -d: -f1 | sort -u
}

_guest_is_nfs_ha_eligible() {
    local vmid="$1"
    local guest_type="$2"
    local storage_id
    local -a storage_ids=()
    local nfs_only=1

    while IFS= read -r storage_id; do
        [[ -z "$storage_id" ]] && continue
        storage_ids+=("$storage_id")
    done < <(_guest_disk_storage_ids "$vmid" "$guest_type")

    if [[ ${#storage_ids[@]} -eq 0 ]]; then
        return 1
    fi

    for storage_id in "${storage_ids[@]}"; do
        if [[ "$storage_id" != "$PVE_NFS_STORAGE_ID" ]]; then
            nfs_only=0
            break
        fi
    done
    [[ "$nfs_only" -eq 1 ]]
}

_ensure_ha_resources() {
    if [[ "${HA_AUTO_ENROLL_NFS_GUESTS:-0}" != "1" ]]; then
        return 0
    fi
    if ! command -v ha-manager >/dev/null 2>&1; then
        return 0
    fi

    local vmid pve_type sid
    while read -r vmid pve_type; do
        [[ -z "$vmid" ]] && continue
        if [[ "$pve_type" == "qemu" ]]; then
            sid="vm:${vmid}"
            guest_type="qemu"
        else
            sid="ct:${vmid}"
            guest_type="lxc"
        fi
        if ha-manager config 2>/dev/null | grep -qF "$sid"; then
            continue
        fi
        if ! _guest_is_nfs_ha_eligible "$vmid" "$guest_type"; then
            _log INFO "Skipping ${sid}: not exclusively on NFS storage '${PVE_NFS_STORAGE_ID}'."
            continue
        fi
        if ha-manager add "$sid" --state started 2>/dev/null; then
            _log INFO "Enrolled ${sid} in HA (NFS-backed)."
        else
            _log WARN "Could not enroll ${sid} in HA."
        fi
    done < <(pvesh get /cluster/resources --type vm --output-format json 2>/dev/null \
        | jq -r '.[] | select((.template // 0) == 0) | "\(.vmid) \(.type)"' 2>/dev/null || true)
}

_ensure_ha_rule() {
    if ! command -v ha-manager >/dev/null 2>&1; then
        _log WARN "ha-manager not found; skipping HA rule."
        return 0
    fi

    local nodes_csv resources_csv
    nodes_csv="$(_ha_nodes_priority_csv)"
    if [[ -z "$nodes_csv" ]]; then
        _log WARN "Could not determine HA node list (set HA_NODES or join a cluster)."
        return 0
    fi

    resources_csv="$(_ha_resource_ids_csv)"
    if [[ -z "$resources_csv" ]]; then
        _log INFO "No HA resources yet (PVE 9 rules require --resources; fencing stays CRM watchdog standby)."
        _log INFO "Do not enroll local-lvm guests. After disks live on ${PVE_NFS_STORAGE_ID}:"
        _log INFO "  ha-manager add vm:<VMID> --state started"
        _log INFO "  ha-manager rules add node-affinity ${HA_GROUP_NAME} --resources vm:<VMID> --nodes ${nodes_csv} --strict 1"
        return 0
    fi

    if ha-manager rules list 2>/dev/null | grep -qF "${HA_GROUP_NAME}"; then
        _log INFO "HA node-affinity rule '${HA_GROUP_NAME}' already exists."
        return 0
    fi

    if ha-manager rules add node-affinity "$HA_GROUP_NAME" \
        --resources "$resources_csv" \
        --nodes "$nodes_csv" \
        --strict 1 \
        --comment "Papita HA pool (watchdog fencing)" 2>/dev/null; then
        _log INFO "Created HA node-affinity rule '${HA_GROUP_NAME}' for nodes: ${nodes_csv}."
        _log INFO "Resources: ${resources_csv}"
        return 0
    fi

    _log WARN "Could not create HA node-affinity rule. Add manually:"
    _log WARN "  ha-manager rules add node-affinity ${HA_GROUP_NAME} --resources ${resources_csv} --nodes ${nodes_csv} --strict 1"
}

_verify_fencing() {
    _log INFO "=== HA fencing (watchdog) ==="
    if command -v ha-manager >/dev/null 2>&1; then
        ha-manager status 2>/dev/null | grep -E '^(fencing|master|lrm)' || true
    fi
    if command -v systemctl >/dev/null 2>&1; then
        _log INFO "watchdog-mux: $(systemctl is-active watchdog-mux 2>/dev/null || echo unknown)"
    fi
    if lsmod 2>/dev/null | grep -q '^softdog'; then
        _log INFO "softdog module loaded."
    else
        _log WARN "softdog module not loaded on $(hostname -s)."
    fi
}

_ensure_ha_group() {
    _ensure_ha_resources
    _ensure_ha_rule
}

_verify_quorum_ha() {
    _log INFO "=== pvecm status ==="
    pvecm status || true
    echo
    if command -v corosync-quorumtool >/dev/null 2>&1; then
        _log INFO "=== corosync-quorumtool -s ==="
        corosync-quorumtool -s || true
        echo
    fi
    if command -v ha-manager >/dev/null 2>&1; then
        _log INFO "=== ha-manager status ==="
        ha-manager status || true
    fi
    if command -v pvesm >/dev/null 2>&1; then
        local line storage_id
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            IFS='|' read -r storage_id _ <<<"$line"
            storage_id="${storage_id//[[:space:]]/}"
            [[ -z "$storage_id" ]] && continue
            _log INFO "=== pvesm status (${storage_id}) ==="
            pvesm status -storage "$storage_id" 2>/dev/null || true
        done < <(_nfs_share_rows)
    fi
}

main() {
    _require_cluster_member
    _load_lab_defaults

    _log INFO "Papita cluster quorum + HA setup"
    _log INFO "  QDevice host: ${QDEVICE_HOST:-<unset>}"
    _log INFO "  TrueNAS NFS:  ${TRUENAS_NFS_SERVER}:${TRUENAS_NFS_EXPORT} → ${PVE_NFS_STORAGE_ID}"
    if [[ -n "${PVE_NFS_SHARE_TABLE:-}" ]]; then
        _log INFO "  NFS share table configured (multiple exports)."
    fi
    _log INFO "  HA group:       ${HA_GROUP_NAME}"
    _log INFO "  HA nodes:       ${HA_NODES:-<all cluster members>}"

    _ensure_cluster_firewall_nfs
    _ensure_nfs_storage
    _ensure_qdevice
    _ensure_ha_group
    _verify_quorum_ha
    _verify_fencing

    _log INFO "Done. Expected: 3 PVE votes + 1 QDevice → quorum 3 (cluster quorate with 2 PVE nodes + QDevice)."
    _log INFO "Fencing: watchdog-mux + softdog on each HA node; ha-manager status should show 'fencing armed'."
}

main "$@"
