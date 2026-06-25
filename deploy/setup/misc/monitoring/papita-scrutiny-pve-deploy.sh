#!/usr/bin/env bash
# shellcheck disable=SC1090,SC1091,SC2029
# Deploy Scrutiny collector LXCs (VMID 101x) on every pvecm-oldtimers node.
# Hub-spoke: privileged collector LXCs (host disk passthrough) → TrueNAS Scrutiny hub.
#
# Run from repo root:
#   ./deploy/setup/misc/monitoring/papita-scrutiny-pve-deploy.sh \
#     --ip-address oldtimers-pve-endpoint.tailf1ad0d.ts.net
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
LXC_DIR="${REPO_ROOT}/deploy/setup/misc/lxc"
COLLECTOR_SCRIPT="${LXC_DIR}/papita-scrutiny-collector-lxc.sh"

# shellcheck source=${REPO_ROOT}/deploy/utils.sh
source "${REPO_ROOT}/deploy/utils.sh"

IP_ADDRESS=""
HUB_URL="${PAPITA_SCRUTINY_HUB_URL:-http://172.16.0.100:31054}"
SCRUTINY_VERSION="${PAPITA_SCRUTINY_VERSION:-0.9.2}"
INTERVAL="${PAPITA_SCRUTINY_INTERVAL:-30min}"
DRY_RUN=0
TARGET_USERNAME="${PAPITA_SSH_USER:-root}"
SSH_COMMON_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)

usage() {
    cat <<EOF
Usage: $(basename "$0") --ip-address HOST [options]

Deploy Scrutiny collector LXCs (1011–1014) on all online cluster nodes.

Options:
  --ip-address HOST       SSH entry (any online member)
  --hub-url URL           Scrutiny hub (default: ${HUB_URL})
  --scrutiny-version VER  Collector tag (default: ${SCRUTINY_VERSION})
  --interval DURATION     Timer interval (default: ${INTERVAL})
  --dry-run               Print remote actions only
  -h, --help              Help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ip-address) IP_ADDRESS="$2"; shift 2 ;;
        --hub-url) HUB_URL="$2"; shift 2 ;;
        --scrutiny-version) SCRUTINY_VERSION="$2"; shift 2 ;;
        --interval) INTERVAL="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h | --help) usage; exit 0 ;;
        *) log ERROR "Unknown option: $1"; usage; exit 1 ;;
    esac
done

if [[ -z "${IP_ADDRESS}" ]]; then
    log ERROR "--ip-address is required."
    usage
    exit 1
fi

if [[ ! -f "${COLLECTOR_SCRIPT}" ]]; then
    log ERROR "Missing ${COLLECTOR_SCRIPT}"
    exit 1
fi

log INFO "Uploading collector bootstrap to ${IP_ADDRESS}..."
if [[ "${DRY_RUN}" -eq 0 ]]; then
    scp "${SSH_COMMON_OPTS[@]}" "${COLLECTOR_SCRIPT}" "${TARGET_USERNAME}@${IP_ADDRESS}:/tmp/papita-scrutiny-collector-lxc.sh"
fi

REMOTE_ENV="HUB_URL=$(printf '%q' "$HUB_URL") SCRUTINY_VERSION=$(printf '%q' "$SCRUTINY_VERSION") INTERVAL=$(printf '%q' "$INTERVAL") DRY_RUN=${DRY_RUN}"

ssh "${SSH_COMMON_OPTS[@]}" "${TARGET_USERNAME}@${IP_ADDRESS}" "${REMOTE_ENV} bash -s" <<'REMOTE'
set -euo pipefail

TEMPLATE="debian-13-standard_13.1-2_amd64.tar.zst"
TEMPLATE_REF="local:vztmpl/${TEMPLATE}"
ROOTFS_SIZE="8"
MEMORY=512
SWAP=512
CPULIMIT="0.5"
GATEWAY="172.16.0.1"
BRIDGE="vmbr0"
COLLECTOR="/tmp/papita-scrutiny-collector-lxc.sh"
SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)

node_vmid() { echo $((1010 + 10#${1##*-})); }
node_ip() { echo "172.16.1.$((100 + 10#${1##*-}))/16"; }
node_storage() {
    case "$1" in
        pvenode-001 | pvenode-004) echo "local-zfs" ;;
        *) echo "truenas-nfs" ;;
    esac
}

ring0_for() {
    jq -r --arg n "$1" '.[] | select((.node // .name // "") == $n) | .ring0_addr // empty' <<<"${CLUSTER_CFG}" | head -n1
}

run_on() {
    local host="$1"
    shift
    ssh "${SSH_OPTS[@]}" "root@${host}" "$@"
}

host_disk_dev_args() {
    local i=0 dev
    while read -r dev; do
        [[ -z "$dev" ]] && continue
        printf ' --dev%d %s,mode=0666' "$i" "$dev"
        i=$((i + 1))
    done < <(smartctl --scan-open 2>/dev/null | awk '{print $1}' | grep -E '^/dev/')
}

harden_ct() {
    local vmid="$1"
    local conf="/etc/pve/lxc/${vmid}.conf"
    grep -q 'lxc.apparmor.profile: unconfined' "$conf" 2>/dev/null || echo 'lxc.apparmor.profile: unconfined' >>"$conf"
    grep -q 'lxc.cgroup2.devices.allow: a' "$conf" 2>/dev/null || echo 'lxc.cgroup2.devices.allow: a' >>"$conf"
    pct reboot "$vmid"
}

attach_disks() {
    local vmid="$1"
    local i=0 dev dev_args=""
    while read -r dev; do
        [[ -z "$dev" ]] && continue
        dev_args+=" -dev${i} ${dev},mode=0666"
        i=$((i + 1))
    done < <(smartctl --scan-open 2>/dev/null | awk '{print $1}' | grep -E '^/dev/')
    if [[ -z "$dev_args" ]]; then
        echo "[WARN] No host block devices for CT ${vmid}; SMART collection may be empty."
        return 0
    fi
    # shellcheck disable=SC2086
    eval "pct set ${vmid} ${dev_args}"
    harden_ct "$vmid"
}

deploy_on_host() {
    local node="$1" host="$2" vmid="$3" ct_ip="$4"
    local storage dev_args
    storage=$(node_storage "$node")

    run_on "$host" "pveam list local 2>/dev/null | grep -qF '${TEMPLATE}'" \
        || run_on "$host" "pveam download local ${TEMPLATE}"

    if run_on "$host" "pct status ${vmid} 2>/dev/null"; then
        echo "[INFO] CT ${vmid} exists on ${node}; updating."
        [[ "${DRY_RUN}" -eq 1 ]] && return 0
        run_on "$host" "pct set ${vmid} -onboot 1 -cpulimit ${CPULIMIT} -memory ${MEMORY} -swap ${SWAP}"
    else
        echo "[INFO] Creating CT ${vmid} on ${node}."
        [[ "${DRY_RUN}" -eq 1 ]] && return 0
        dev_args=$(run_on "$host" "$(declare -f host_disk_dev_args); host_disk_dev_args")
        # shellcheck disable=SC2086
        run_on "$host" "pct create ${vmid} ${TEMPLATE_REF} \
            --ostype debian --arch amd64 --hostname scrutiny-${node} \
            --cores 1 --cpulimit ${CPULIMIT} --memory ${MEMORY} --swap ${SWAP} \
            --rootfs ${storage}:${ROOTFS_SIZE} \
            --net0 name=eth0,bridge=${BRIDGE},ip=${ct_ip},gw=${GATEWAY},firewall=0 \
            --unprivileged 0 --onboot 1 --tags 'lxc;monitoring;scrutiny' \
            --description 'Scrutiny SMART collector (privileged, host disk passthrough)' \
            ${dev_args} --start 1"
    fi

    run_on "$host" "$(declare -f harden_ct attach_disks host_disk_dev_args); attach_disks ${vmid}"
    run_on "$host" "test -f ${COLLECTOR} || true"
    scp "${SSH_OPTS[@]}" "${COLLECTOR}" "root@${host}:/tmp/papita-scrutiny-collector-lxc.sh"
    run_on "$host" "pct push ${vmid} /tmp/papita-scrutiny-collector-lxc.sh /root/papita-scrutiny-collector-lxc.sh"
    run_on "$host" "pct exec ${vmid} -- bash -c $(printf '%q' \
        "export PAPITA_SCRUTINY_HUB_URL='${HUB_URL}' PAPITA_SCRUTINY_VERSION='${SCRUTINY_VERSION}' PAPITA_SCRUTINY_HOST_ID='${node}' PAPITA_SCRUTINY_INTERVAL='${INTERVAL}'; bash /root/papita-scrutiny-collector-lxc.sh")"
    run_on "$host" "pct exec ${vmid} -- systemctl start papita-scrutiny-collector.service"
    run_on "$host" "pct exec ${vmid} -- smartctl --scan-open 2>/dev/null | head -5"
}

mapfile -t NODES < <(pvesh get /cluster/resources --type node --output-format json | jq -r '.[] | select(.status=="online") | .node' | sort)
CLUSTER_CFG=$(pvesh get /cluster/config/nodes --output-format json 2>/dev/null || echo "[]")
CLUSTER_CFG=$(jq 'if type == "object" and ((.data | type) == "array") then .data elif type == "array" then . else [] end' <<<"${CLUSTER_CFG}")

echo "[INFO] Hub ${HUB_URL} collector v${SCRUTINY_VERSION} interval ${INTERVAL}"

for node in "${NODES[@]}"; do
    vmid=$(node_vmid "$node")
    ct_ip=$(node_ip "$node")
    host=$(ring0_for "$node")
    if [[ -z "$host" ]]; then
        echo "[WARN] No ring0 for ${node}; skip"
        continue
    fi
    echo "=== ${node} CT ${vmid} @ ${ct_ip} host ${host} ==="
    deploy_on_host "$node" "$host" "$vmid" "$ct_ip"
done

echo "[INFO] Done. Open ${HUB_URL} to verify PVE node disks."
REMOTE

log INFO "Scrutiny PVE collector deployment finished."
