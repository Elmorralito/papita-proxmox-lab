#!/usr/bin/env bash
# Scrutiny collector for privileged Debian LXC with host /dev bind (SMART via smartctl).
# Hub-spoke: collectors on each PVE node → central Scrutiny hub (TrueNAS app in this lab).
#
# Run inside the CT as root after /dev is mounted from the Proxmox host:
#   pct push <vmid> .../papita-scrutiny-collector-lxc.sh /root/papita-scrutiny-collector-lxc.sh
#   pct exec <vmid> -- bash /root/papita-scrutiny-collector-lxc.sh
#
# Optional env file:
#   export $(grep -v '^#' /root/scrutiny-lxc.env | xargs) && bash /root/papita-scrutiny-collector-lxc.sh
set -euo pipefail

SCRUTINY_VERSION="${PAPITA_SCRUTINY_VERSION:-0.9.2}"
HUB_URL="${PAPITA_SCRUTINY_HUB_URL:-http://172.16.0.100:31054}"
HOST_ID="${PAPITA_SCRUTINY_HOST_ID:-$(hostname -s)}"
INTERVAL="${PAPITA_SCRUTINY_INTERVAL:-30min}"

INSTALL_DIR="/opt/scrutiny"
BIN_PATH="${INSTALL_DIR}/bin/scrutiny-collector-metrics"
CONFIG_PATH="${INSTALL_DIR}/config/collector.yaml"
SERVICE_PATH="/etc/systemd/system/papita-scrutiny-collector.service"
TIMER_PATH="/etc/systemd/system/papita-scrutiny-collector.timer"

if [[ "${PAPITA_SCRUTINY_LXC_DISABLE:-0}" == "1" ]]; then
    systemctl disable --now papita-scrutiny-collector.timer 2>/dev/null || true
    echo "[INFO] Scrutiny collector disabled in this CT."
    exit 0
fi

if ! command -v apt-get >/dev/null 2>&1; then
    echo "[ERROR] apt-get not found; is this a Debian-based CT?"
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y smartmontools curl ca-certificates

if [[ ! -d /dev ]] || ! smartctl --scan-open >/dev/null 2>&1; then
    echo "[WARN] smartctl --scan-open failed — ensure privileged CT with host /dev bind (mp0: /dev,mp=/dev)."
fi

install -d -m 0755 "${INSTALL_DIR}/bin" "${INSTALL_DIR}/config"
curl -fsSL \
    "https://github.com/AnalogJ/scrutiny/releases/download/v${SCRUTINY_VERSION}/scrutiny-collector-metrics-linux-amd64" \
    -o "${BIN_PATH}"
chmod +x "${BIN_PATH}"

{
    echo "version: 1"
    echo "commands:"
    echo "  metrics_smartctl_bin: /usr/sbin/smartctl"
    echo "host:"
    echo "  id: \"${HOST_ID}\""
} >"${CONFIG_PATH}"

cat >"${SERVICE_PATH}" <<EOF
[Unit]
Description=Papita Scrutiny SMART collector (${HOST_ID})
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=PATH=/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=${BIN_PATH} run --api-endpoint ${HUB_URL}
EOF

cat >"${TIMER_PATH}" <<EOF
[Unit]
Description=Periodic Scrutiny collector (${HOST_ID})

[Timer]
OnBootSec=5min
OnUnitActiveSec=${INTERVAL}
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now papita-scrutiny-collector.timer
systemctl start papita-scrutiny-collector.service

echo "[INFO] Scrutiny collector configured."
echo "[INFO] Hub: ${HUB_URL}  Host ID: ${HOST_ID}  Version: v${SCRUTINY_VERSION}  Interval: ${INTERVAL}"
echo "[INFO] Devices:"
smartctl --scan-open 2>/dev/null || true
systemctl status papita-scrutiny-collector.timer --no-pager | head -n 8 || true
