#!/usr/bin/env bash
# Proxmox CT firewall for Uptime Kuma (LXC 1004): allow WebUI from LAN + Tailscale.
set -euo pipefail

VMID="${PAPITA_UPTIME_KUMA_VMID:-1004}"
PORT="${PAPITA_UPTIME_KUMA_PORT:-3001}"
LAN_CIDR="${PAPITA_LAN_CIDR:-172.16.0.0/16}"
TS_CIDR="${PAPITA_TAILSCALE_CIDR:-100.64.0.0/10}"
CT_FW="/etc/pve/firewall/${VMID}.fw"

if [[ ! -d /etc/pve/firewall ]]; then
    echo "[ERROR] /etc/pve/firewall missing; is this a Proxmox node?"
    exit 1
fi

cat >"${CT_FW}" <<EOF
[OPTIONS]
enable: 1

[RULES]
IN ACCEPT -source ${LAN_CIDR} -p tcp -dport ${PORT} -log nolog
IN ACCEPT -source ${TS_CIDR} -p tcp -dport ${PORT} -log nolog
IN ACCEPT -i lo -log nolog
EOF

echo "[INFO] Wrote ${CT_FW} (TCP ${PORT} from ${LAN_CIDR} and ${TS_CIDR})"
pve-firewall restart
echo "[INFO] pve-firewall restarted."
