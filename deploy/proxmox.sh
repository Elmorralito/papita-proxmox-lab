#!/usr/bin/env bash
# shellcheck disable=SC1090,SC1091,SC2029
set -euo pipefail

ENV=
IP_ADDRESS=
TARGET_USERNAME="root"
# Optional shared SSH password for peer nodes (get-temp, etc.): env PAPITA_SSH_PASSWORD / SSH_CLUSTER_PASSWORD, or prompt.
# Password auth for scripted capture requires sshpass(1). Prefer SSH keys on all cluster members.
SSH_CLUSTER_PASSWORD="${SSH_CLUSTER_PASSWORD:-${PAPITA_SSH_PASSWORD:-}}"
# Populated by get_cluster_nodes(): Proxmox node names from pvesh (same as JSON .node, e.g. pvenode-001).
CLUSTER_NODE_IDS=()
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

if ! command -v jq >/dev/null 2>&1; then
    log "ERROR" "jq utility is not installed."
    exit 255
fi

if ! command -v ssh >/dev/null 2>&1 || ! command -v scp >/dev/null 2>&1; then
    log "ERROR" "SSH utilities are not installed."
    exit 255
fi

_deploy_tree_via_tar() {
    local src_dir="$1"
    local remote_dir="$2"
    shift 2
    local -a excludes=("$@")
    local -a tar_cmd=(tar -C "$src_dir")
    local pattern

    # macOS bsdtar embeds com.apple.provenance xattrs; GNU tar on PVE warns on extract.
    if [[ "$(uname -s)" == "Darwin" ]]; then
        tar_cmd+=(--disable-copyfile)
    fi

    for pattern in "${excludes[@]}"; do
        tar_cmd+=(--exclude="$pattern")
    done
    tar_cmd+=(-cf - .)

    ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" mkdir -p "$remote_dir"
    COPYFILE_DISABLE=1 "${tar_cmd[@]}" | ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" \
        "tar -C ${remote_dir} -xf - --warning=no-unknown-keyword"
}

setup_node() {
    local required_local_file
    for required_local_file in \
        src/bash/setup-pve-node.sh \
        src/bash/misc/tailscale/default.gateways.list \
        src/bash/misc/tailscale/default.lan.routes.list \
        src/bash/misc/tailscale/default.tags.list \
        src/python/misc/cluster/discover_hosts.py \
        src/python/data/default.hosts.list; do
        if [[ ! -f "$PROJECT_PATH/$required_local_file" ]]; then
            log "ERROR" "Local bundle incomplete: missing ${required_local_file}"
            exit 255
        fi
    done

    log "WARN" "Replacing ${TARGET_REMOTE_PATH}/deploy on $IP_ADDRESS (removing old copy before transfer)."
    # Pass path as argv (not inside one remote "…" string) so SC2029 does not apply; path expands locally by design.
    ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" rm -rf -- "${TARGET_REMOTE_PATH}/deploy"

    log "INFO" "Deploying setup-pve-node bundle to $IP_ADDRESS:$TARGET_REMOTE_PATH/deploy."
    ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" mkdir -p "${TARGET_REMOTE_PATH}/deploy"
    # tar preserves misc/tailscale/ reliably (macOS scp -r src/bash/. can skip nested dirs).
    _deploy_tree_via_tar "$PROJECT_PATH/src/bash" "${TARGET_REMOTE_PATH}/deploy" \
        __pycache__ '*.pyc' misc/cluster
    _deploy_tree_via_tar "$PROJECT_PATH/src/python" "${TARGET_REMOTE_PATH}/deploy/python" \
        __pycache__ '*.pyc'
    scp "${SSH_COMMON_OPTS[@]}" "$PROJECT_PATH/deploy/utils.sh" "$TARGET_USERNAME@$IP_ADDRESS:$TARGET_REMOTE_PATH/deploy/utils.sh"
    scp "${SSH_COMMON_OPTS[@]}" "$PROJECT_PATH/deploy/usage.sh" "$TARGET_USERNAME@$IP_ADDRESS:$TARGET_REMOTE_PATH/deploy/usage.sh"
    ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" mkdir -p "${TARGET_REMOTE_PATH}/deploy/data"
    scp "${SSH_COMMON_OPTS[@]}" "$PROJECT_PATH/deploy/data/setup-pve-node.usage.txt" "$TARGET_USERNAME@$IP_ADDRESS:$TARGET_REMOTE_PATH/deploy/data/setup-pve-node.usage.txt"

    log "INFO" "Deployed src/bash/, src/python/ (misc/cluster + data), utils.sh, usage.sh, and data/setup-pve-node.usage.txt to $IP_ADDRESS:$TARGET_REMOTE_PATH/deploy."

    ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" chmod -R a+rx "${TARGET_REMOTE_PATH}/deploy"

    local required_deploy_file
    for required_deploy_file in \
        setup-pve-node.sh \
        misc/tailscale/default.gateways.list \
        misc/tailscale/default.lan.routes.list \
        misc/tailscale/default.tags.list \
        python/misc/cluster/discover_hosts.py \
        python/data/default.hosts.list; do
        if ! ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" \
            "test -f ${TARGET_REMOTE_PATH}/deploy/${required_deploy_file}"; then
            log "ERROR" "Deploy bundle incomplete on ${IP_ADDRESS}: missing ${required_deploy_file}"
            exit 255
        fi
    done

    log "INFO" "Set permissions for $IP_ADDRESS:$TARGET_REMOTE_PATH/deploy (python bundle at .../deploy/python/)."

    # -tt: allocate a remote PTY so setup-pve-node.sh prompts (read -e/-p) work even if stdin here is not a TTY.
    # Remote TERM fallback when the client did not set one (e.g. some IDE terminals).
    ssh "${SSH_COMMON_OPTS[@]}" -tt "$TARGET_USERNAME@$IP_ADDRESS" "cd ${TARGET_REMOTE_PATH}/deploy && export TERM=\${TERM:-xterm-256color} && exec bash setup-pve-node.sh"
}

get_cluster_nodes() {
    local json_out
    if ! json_out=$(ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" "pvesh get /cluster/resources --type node --output-format json"); then
        log "ERROR" "pvesh get /cluster/resources failed on $IP_ADDRESS."
        return 1
    fi
    # shellcheck disable=SC2207
    CLUSTER_NODE_IDS=($(jq -r '.[] | select(.type == "node" and .status == "online") | .node // empty' <<<"${json_out}" 2>/dev/null || true))
    if [[ ${#CLUSTER_NODE_IDS[@]} -eq 0 ]]; then
        log "WARN" "No cluster nodes parsed from JSON (empty array)."
    else
        log "INFO" "Cluster node ids:"
        log "TRACE" "${CLUSTER_NODE_IDS[*]}"
    fi
}

# Map cluster node name → corosync ring0_addr (IP or hostname) from normalized JSON array.
# Prints one line; empty if unknown. Caller uses $IP_ADDRESS for the node marked (local) in pvecm.
_pve_cluster_ring0_addr_for_node() {
    local nodename="$1" json="$2"
    jq -r --arg n "$nodename" '
        .[]
        | select((.node // .name // "") == $n)
        | .ring0_addr // empty
    ' <<<"$json" | head -n1
}

get_local_node() {
    local pvecm_out local_node
    if ! pvecm_out=$(ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" "pvecm nodes"); then
        log "ERROR" "pvecm nodes failed on $IP_ADDRESS."
        return 1
    fi
    local_node=$(awk '
        /\(local\)/ {
            for (i = 1; i <= NF; i++) {
                if ($i == "(local)") {
                    print $(i - 1)
                    exit 0
                }
            }
        }
    ' <<<"$pvecm_out")
    if [[ -z "$local_node" ]]; then
        log "ERROR" "No node marked (local) in pvecm nodes output on $IP_ADDRESS."
        return 1
    fi
    printf '%s' "$local_node"
    return 0
}

start_cluster() {
    local_node=$(get_local_node)
    if [[ -z "$local_node" ]]; then
        log "ERROR" "No local node found."
        return 255
    fi
    log "INFO" "Local node: $local_node"
    get_cluster_nodes
    if [[ ${#CLUSTER_NODE_IDS[@]} -eq 0 ]]; then
        log "WARN" "No cluster nodes found."
        return 255
    fi
    log "INFO" "Sending Wake-on-LAN to cluster nodes..."
    ERROR_COUNT=0
    for node in "${CLUSTER_NODE_IDS[@]}"; do
        if [[ "$node" == "$local_node" ]]; then
            log "INFO" "Skipping Wake-on-LAN to local node: $node"
            continue
        fi
        log "INFO" "Sending Wake-on-LAN to cluster node: $node"
        ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" "pvenode wakeonlan \"${node}\"" || {
            log "ERROR" "Failed to send Wake-on-LAN to cluster node: $node"
            ((ERROR_COUNT++))
        }
    done
    log "INFO" "Wake-on-LAN sent to cluster nodes."
    return $ERROR_COUNT
}

stop_cluster() {
    # Per-node API calls (pvesh … /nodes/<name>/…) target each cluster member by name.
    # Never run plain shutdown only on $IP_ADDRESS for every peer—that always hits the SSH
    # entry host and triggers "halt already in progress" on the next call.

    local_node=$(get_local_node)
    if [[ -z "$local_node" ]]; then
        log "ERROR" "No local node found."
        return 255
    fi
    get_cluster_nodes
    if [[ ${#CLUSTER_NODE_IDS[@]} -eq 0 ]]; then
        log "WARN" "No cluster nodes found."
        return 255
    fi

    _pve_node_name_safe() {
        local n=$1
        [[ -n "$n" && "$n" != *[^a-zA-Z0-9._-]* ]]
    }

    log "INFO" "Cluster shutdown: stop guests then request hypervisor shutdown (pvesh per node)."
    ERROR_COUNT=0

    for node in "${CLUSTER_NODE_IDS[@]}"; do
        if ! _pve_node_name_safe "$node"; then
            log "ERROR" "Invalid node name (not passed to pvesh): $node"
            ERROR_COUNT=$((ERROR_COUNT + 1))
            continue
        fi
        if [[ "$node" == "$local_node" ]]; then
            continue
        fi
        log "INFO" "Stopping guests on ${node}..."
        ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" "pvesh create /nodes/${node}/stopall" || {
            log "WARN" "pvesh stopall failed for ${node} (offline, unreachable, or permission); continuing."
            ERROR_COUNT=$((ERROR_COUNT + 1))
        }
        log "INFO" "Requesting hypervisor shutdown for ${node}..."
        ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" "pvesh create /nodes/${node}/status --command shutdown" || {
            log "WARN" "Hypervisor shutdown request failed for ${node}."
            ERROR_COUNT=$((ERROR_COUNT + 1))
        }
    done

    log "INFO" "Stopping guests on local node (${local_node})..."
    ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" "pvenode stopall" || {
        log "ERROR" "pvenode stopall failed on local node."
        ERROR_COUNT=$((ERROR_COUNT + 1))
    }

    if [[ "${SHUTDOWN_LOCAL_NODE:-0}" == "1" ]]; then
        if [[ "${YES:-0}" == "1" ]]; then
            confirm="y"
        else
            prompt_until_yn "Are you sure you want to shutdown the local node? (y/n): " confirm
        fi
        if [ "$confirm" != "y" ]; then
            log "INFO" "Skipping local node shutdown..."
            return 0
        fi
        log "INFO" "Requesting hypervisor shutdown for local node (${local_node})..."
        ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" "pvesh create /nodes/${local_node}/status --command shutdown" || {
            log "ERROR" "Hypervisor shutdown request failed for local node ${local_node}."
            ERROR_COUNT=$((ERROR_COUNT + 1))
        }
    fi

    log "INFO" "Cluster shutdown sequence finished."
    return "$ERROR_COUNT"
}

ACTION="$1"
shift

check_action_help usage_proxmox "$ACTION"

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --ip-address | -ip)
            IP_ADDRESS="$2"
            shift 2
            ;;
        --hostname | -hn)
            HOSTNAME="$2"
            shift 2
            ;;
        --shutdown-local-node | -sln)
            SHUTDOWN_LOCAL_NODE=1
            shift 1
            ;;
        --yes | -y)
            YES=1
            shift 1
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

# Separate connection for password-based attempts (avoid mixing with ControlMaster key session).
SSH_PW_EXTRA_OPTS=(
    -o ControlMaster=no
    -o ControlPath=none
    -o StrictHostKeyChecking=accept-new
    -o ConnectTimeout=15
)

# Run remote_cmd (single shell string) on host; print captured stdout. Returns 0 on success.
# Order: try public-key (BatchMode); then sshpass + SSH_CLUSTER_PASSWORD (from env if set); then prompt (hidden) per host if needed.
_pve_ssh_capture() {
    local host="$1" remote_cmd="$2"
    local quoted out
    quoted=$(printf '%q' "$remote_cmd")

    if out=$(ssh "${SSH_COMMON_OPTS[@]}" -o BatchMode=yes -o ConnectTimeout=15 "${TARGET_USERNAME}@${host}" "exec bash -lc $quoted" 2>/dev/null); then
        printf '%s' "$out"
        return 0
    fi

    if ! command -v sshpass &>/dev/null; then
        log "ERROR" "SSH to ${TARGET_USERNAME}@${host} failed (no key). Install sshpass(1) for password auth, set PAPITA_SSH_PASSWORD (or SSH_CLUSTER_PASSWORD), or add a public key on this host."
        return 1
    fi

    if [[ -n "${SSH_CLUSTER_PASSWORD:-}" ]]; then
        if out=$(SSHPASS="${SSH_CLUSTER_PASSWORD}" sshpass -e ssh "${SSH_PW_EXTRA_OPTS[@]}" "${TARGET_USERNAME}@${host}" "exec bash -lc $quoted" 2>/dev/null); then
            printf '%s' "$out"
            return 0
        fi
        log "WARN" "SSH with shared password failed for ${TARGET_USERNAME}@${host}; try another password for this node."
    fi

    if [[ ! -t 0 ]]; then
        log "ERROR" "Cannot prompt for SSH password (stdin is not a TTY). Set PAPITA_SSH_PASSWORD (or SSH_CLUSTER_PASSWORD), or use SSH keys for ${TARGET_USERNAME}@${host}."
        return 1
    fi
    read -r -s -p "SSH password for ${TARGET_USERNAME}@${host}: " SSH_CLUSTER_PASSWORD || return 1
    echo
    if out=$(SSHPASS="${SSH_CLUSTER_PASSWORD}" sshpass -e ssh "${SSH_PW_EXTRA_OPTS[@]}" "${TARGET_USERNAME}@${host}" "exec bash -lc $quoted" 2>/dev/null); then
        printf '%s' "$out"
        return 0
    fi
    log "ERROR" "SSH to ${TARGET_USERNAME}@${host} failed after password retry."
    return 1
}

# For each cluster member: resolve SSH target (entry IP for local node, else ring0_addr), run remote_cmd, call visitor(node_name, stdout).
# Requires: CLUSTER_NODE_IDS populated (call get_cluster_nodes first), local_node, cluster_cfg_json array JSON.
_pve_cluster_for_each_remote_ssh() {
    local local_node="$1" cluster_cfg_json="$2" remote_cmd="$3"
    local visitor="$4"
    local node target_host out

    for node in "${CLUSTER_NODE_IDS[@]}"; do
        if [[ "$node" == "$local_node" ]]; then
            target_host="$IP_ADDRESS"
        else
            target_host=$(_pve_cluster_ring0_addr_for_node "$node" "$cluster_cfg_json")
            if [[ -z "$target_host" ]]; then
                log "WARN" "No ring0_addr for cluster node $node in /cluster/config/nodes — cannot SSH. Add resolvable host or fix cluster config."
                continue
            fi
        fi
        log "INFO" "Running remote command on node $node via ${TARGET_USERNAME}@${target_host}"
        if ! out=$(_pve_ssh_capture "$target_host" "$remote_cmd"); then
            log "ERROR" "Remote command failed on $node (${TARGET_USERNAME}@${target_host})."
            continue
        fi
        if [[ -z "$out" ]]; then
            log "ERROR" "Empty output from $node (${TARGET_USERNAME}@${target_host})."
            continue
        fi
        "$visitor" "$node" "$out"
    done
}

_pve_print_sensors_table() {
    local node="$1" sensors_json="$2"
    {
        echo "Node: $node"
        echo "---------------------------------------"
        echo "DEVICE/CORE                INPUT (°C)"
        echo "---------------------------------------"
        echo "$sensors_json" | jq -r '
                to_entries[]
                | .key as $chip
                | .value as $chipval
                | $chipval | to_entries[]
                | .key as $field
                | .value as $subval
                | if ( ($subval|type) == "object" and ($subval|has("temp1_input") or . as $root | keys_unsorted | map(startswith("temp") and endswith("_input")) | any) )
                    then
                        [$chip, $field, (if $subval.temp1_input then $subval.temp1_input else
                            [$subval | to_entries[] | select(.key|startswith("temp") and endswith("_input")) | .value] | first // null end)]
                        | @tsv
                    elif ($subval|type) == "object"
                    then
                        [$chip, $field, ($subval | to_entries[] | select(.key|endswith("_input")) | .value)]
                        | @tsv
                    else empty end
                ' | awk -F"\t" '
                    NF==3 && $3 ~ /^[0-9.]+$/ { printf "%-26s %8.2f\n", $1 " / " $2, $3 }
                '
        echo ""
    }
}

get_cluster_temperature() {
    local local_node cluster_cfg_json

    if ! local_node=$(get_local_node); then
        log "ERROR" "Could not determine local Proxmox node name (pvecm nodes on $IP_ADDRESS)."
        return 255
    fi
    log "INFO" "Local cluster node: $local_node (SSH entry: ${TARGET_USERNAME}@${IP_ADDRESS})"

    get_cluster_nodes
    if [[ ${#CLUSTER_NODE_IDS[@]} -eq 0 ]]; then
        log "WARN" "No cluster nodes found."
        return 255
    fi

    cluster_cfg_json=$(ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" \
        "pvesh get /cluster/config/nodes --output-format json 2>/dev/null" || true)
    if [[ -z "$cluster_cfg_json" ]] || ! jq -e . >/dev/null 2>&1 <<<"$cluster_cfg_json"; then
        log "WARN" "Could not read /cluster/config/nodes JSON; peer addresses may be missing (non-cluster or API error)."
        cluster_cfg_json="[]"
    else
        cluster_cfg_json=$(jq 'if type == "object" and ((.data | type) == "array") then .data elif type == "array" then . else [] end' <<<"$cluster_cfg_json")
    fi

    _pve_cluster_for_each_remote_ssh "$local_node" "$cluster_cfg_json" "sensors -j 2>/dev/null" _pve_print_sensors_table
}

_proxmox_ssh_cleanup() {
    ssh "${SSH_COMMON_OPTS[@]}" -O exit "${TARGET_USERNAME}@${IP_ADDRESS}" 2>/dev/null || true
}
trap _proxmox_ssh_cleanup EXIT

if ! ssh "${SSH_COMMON_OPTS[@]}" "$TARGET_USERNAME@$IP_ADDRESS" "true"; then
    log "ERROR" "Failed to connect to $IP_ADDRESS using username $TARGET_USERNAME."
    usage_proxmox
fi

log "INFO" "Connected to $IP_ADDRESS using username $TARGET_USERNAME (SSH multiplexing enabled)."

case "$ACTION" in
    get-temp | get-temperature)
        get_cluster_temperature
        ;;
    setup-node)
        setup_node
        ;;
    local-node)
        local_node=$(get_local_node)
        if [[ -z "$local_node" ]]; then
            log "ERROR" "No local node found."
            return 255
        fi
        log "INFO" "Local node: $local_node"
        ;;
    cluster-nodes)
        get_cluster_nodes
        ;;
    start-cluster)
        start_cluster
        ;;
    stop-cluster)
        stop_cluster
        ;;
    *)
        log "ERROR" "Invalid action: $ACTION."
        usage_proxmox
        ;;
esac

log "INFO" "Done."
