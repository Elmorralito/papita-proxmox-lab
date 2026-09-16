#!/bin/bash
# Optional extras on the dedicated QDevice host (NOT PVE / NOT TrueNAS):
# Tailscale admin reachability + Netdata dashboard + prometheus-node-exporter.
# Primary role remains corosync-qnetd (see qdevice-server-bootstrap.sh).
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "[ERROR] Run as root on the QDevice host." >&2
    exit 1
fi

if command -v pvecm >/dev/null 2>&1; then
    echo "[ERROR] Do not run on a Proxmox VE node." >&2
    exit 1
fi

HOSTNAME_TS="${PAPITA_QDEVICE_TS_HOSTNAME:-raspi-qdevice-oldtimers}"
TS_AUTH_KEY="${TAILSCALE_AUTH_KEY:-${TS_AUTHKEY:-}}"

echo "[INFO] Installing Tailscale (if needed)..."
if ! command -v tailscale >/dev/null 2>&1; then
    curl -fsSL https://tailscale.com/install.sh -o /tmp/tailscale-install.sh
    bash /tmp/tailscale-install.sh
    rm -f /tmp/tailscale-install.sh
fi
systemctl enable --now tailscaled

echo "[INFO] Installing prometheus-node-exporter..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y prometheus-node-exporter
systemctl enable --now prometheus-node-exporter

if ! systemctl list-unit-files 2>/dev/null | grep -q '^netdata'; then
    echo "[INFO] Installing Netdata via kickstart..."
    curl -fsSL https://get.netdata.cloud/kickstart.sh -o /tmp/netdata-kickstart.sh
    bash /tmp/netdata-kickstart.sh --non-interactive --stable-channel --dont-wait --disable-telemetry \
        || bash /tmp/netdata-kickstart.sh --non-interactive --stable-channel --dont-wait
    rm -f /tmp/netdata-kickstart.sh
fi

mkdir -p /etc/netdata/conf.d
cat >/etc/netdata/conf.d/papita-bind.conf <<'EOF'
[web]
    bind to = *
    allow connections from = localhost 172.16.* 192.168.78.* 100.*
EOF
systemctl enable --now netdata
systemctl restart netdata

echo "[INFO] Bringing Tailscale up (hostname=${HOSTNAME_TS})..."
ts_args=(up --hostname="${HOSTNAME_TS}" --accept-dns --ssh --reset)
if [[ -n "${TS_AUTH_KEY}" ]]; then
    ts_args+=(--auth-key="${TS_AUTH_KEY}")
    if [[ -n "${PAPITA_TS_ADVERTISE_TAGS:-}" ]]; then
        ts_args+=(--advertise-tags="${PAPITA_TS_ADVERTISE_TAGS}")
    else
        ts_args+=(--advertise-tags=tag:private-node,tag:server-node)
    fi
fi
tailscale "${ts_args[@]}"

echo "[INFO] Tailscale: $(tailscale ip -4 2>/dev/null || echo pending-login)"
echo "[INFO] Netdata:          http://$(hostname -I | awk '{print $1}'):19999"
echo "[INFO] Node exporter:    http://$(hostname -I | awk '{print $1}'):9100/metrics"
