#!/bin/bash
# Run on the dedicated QDevice host (Debian/Ubuntu), NOT on PVE or TrueNAS.
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "[ERROR] Run as root on the QDevice host." >&2
    exit 1
fi

if command -v pvecm >/dev/null 2>&1; then
    echo "[ERROR] This script must not run on a Proxmox VE node." >&2
    exit 1
fi

echo "[INFO] Installing corosync-qnetd..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y corosync-qnetd

systemctl enable --now corosync-qnetd
systemctl is-active corosync-qnetd

echo "[INFO] QDevice server ready. From a PVE cluster member run:"
echo "       pvecm qdevice setup $(hostname -I | awk '{print $1}')"
echo "       (or use the IP listed in misc/cluster/default.qdevice.host)"
