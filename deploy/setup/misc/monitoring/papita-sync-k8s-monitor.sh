#!/usr/bin/env bash
# Copy k8s-monitor stack (no secrets) into LXC 231 and reload Prometheus.
# Grafana lives on the QDevice Pi (papita-qdevice-grafana.sh), not in this CT.
# Run on the PVE node that currently hosts the CT (or any member with pct).
set -euo pipefail

VMID="${PAPITA_K8S_MONITOR_VMID:-231}"
DEST="${PAPITA_K8S_MONITOR_DEST:-/opt/k8s-monitor}"
SCRIPT_DIR="$(dirname "$(realpath "$0")")"
SRC="${SCRIPT_DIR}/k8s-monitor"

if [[ ! -d "$SRC" ]]; then
    echo "[ERROR] missing ${SRC}" >&2
    exit 1
fi
if ! command -v pct >/dev/null 2>&1; then
    echo "[ERROR] pct not found; run on a Proxmox node." >&2
    exit 1
fi
if [[ "$(pct status "$VMID" 2>/dev/null || true)" != *running* ]]; then
    echo "[ERROR] CT ${VMID} is not running." >&2
    exit 1
fi

pct exec "$VMID" -- mkdir -p \
    "${DEST}/prometheus/rules" \
    "${DEST}/alertmanager" \
    "${DEST}/secrets"

push_file() {
    local rel="$1"
    pct exec "$VMID" -- tee "${DEST}/${rel}" <"${SRC}/${rel}" >/dev/null
}

push_file docker-compose.yml
push_file prometheus/prometheus.yml
push_file prometheus/rules/k8s.yml
push_file prometheus/rules/pve.yml
push_file alertmanager/alertmanager.yml

if ! pct exec "$VMID" -- test -s "${DEST}/secrets/k8s-bearer.token"; then
    echo "[WARN] ${DEST}/secrets/k8s-bearer.token missing on CT; Kubernetes scrapes need it."
fi

# --remove-orphans drops the retired grafana container; the grafana_data volume is kept.
pct exec "$VMID" -- bash -lc "cd ${DEST} && docker compose up -d --remove-orphans"
pct exec "$VMID" -- bash -lc "wget -qO- --post-data='' http://127.0.0.1:9090/-/reload && echo '[INFO] prometheus reloaded'"
echo "[INFO] synced monitoring stack to CT ${VMID}:${DEST}"
