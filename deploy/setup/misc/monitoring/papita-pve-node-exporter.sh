#!/usr/bin/env bash
# Install prometheus-node-exporter on this PVE node (scrape :9100 from k8s-monitor).
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "[ERROR] Run as root on a Proxmox VE node." >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive

if ! dpkg -s prometheus-node-exporter >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y prometheus-node-exporter
fi

systemctl enable --now prometheus-node-exporter
echo "[INFO] prometheus-node-exporter: $(systemctl is-active prometheus-node-exporter) on $(hostname -s)"
ss -lnt | grep -q ':9100' || echo "[WARN] nothing listening on :9100"
