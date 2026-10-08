#!/usr/bin/env bash
# Copy k8s-monitor stack (no secrets) into LXC 231 and reload Prometheus / Grafana.
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
    "${DEST}/grafana/provisioning/dashboards/json" \
    "${DEST}/grafana/provisioning/datasources" \
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
push_file grafana/provisioning/datasources/prometheus.yml
push_file grafana/provisioning/dashboards/provider.yml
push_file grafana/provisioning/dashboards/json/k8s.json
push_file grafana/provisioning/dashboards/json/pve.json

if ! pct exec "$VMID" -- test -f "${DEST}/grafana.env"; then
    pct exec "$VMID" -- tee "${DEST}/grafana.env" <"${SRC}/grafana.env.example" >/dev/null
    pct exec "$VMID" -- chmod 600 "${DEST}/grafana.env"
    echo "[WARN] wrote ${DEST}/grafana.env from example; set GF_SECURITY_ADMIN_PASSWORD on the CT."
fi
if ! pct exec "$VMID" -- test -s "${DEST}/secrets/k8s-bearer.token"; then
    echo "[WARN] ${DEST}/secrets/k8s-bearer.token missing on CT; Kubernetes scrapes need it."
fi

pct exec "$VMID" -- bash -lc "cd ${DEST} && docker compose up -d"
pct exec "$VMID" -- bash -lc "wget -qO- --post-data='' http://127.0.0.1:9090/-/reload && echo '[INFO] prometheus reloaded'"
pct exec "$VMID" -- bash -lc "cd ${DEST} && docker compose restart grafana"
echo "[INFO] synced monitoring stack to CT ${VMID}:${DEST}"
