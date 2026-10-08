#!/usr/bin/env bash
# Proxmox CT firewall for k8s-monitor (LXC 231): Grafana / Prometheus / Alertmanager from LAN + Tailscale Grafana.
set -euo pipefail

VMID="${PAPITA_K8S_MONITOR_VMID:-231}"
LAN_CIDR="${PAPITA_LAN_CIDR:-172.16.0.0/16}"
TS_CIDR="${PAPITA_TAILSCALE_CIDR:-100.64.0.0/10}"
CT_FW="/etc/pve/firewall/${VMID}.fw"
SCRIPT_DIR="$(dirname "$(realpath "$0")")"
SRC="${SCRIPT_DIR}/firewall/231.fw"

if [[ ! -d /etc/pve/firewall ]]; then
    echo "[ERROR] /etc/pve/firewall missing; is this a Proxmox node?" >&2
    exit 1
fi

if [[ -f "$SRC" ]]; then
    sed \
        -e "s#172.16.0.0/16#${LAN_CIDR}#g" \
        -e "s#100.64.0.0/10#${TS_CIDR}#g" \
        "$SRC" >"${CT_FW}"
else
    cat >"${CT_FW}" <<EOF
[OPTIONS]
enable: 1

[RULES]
IN ACCEPT -source ${LAN_CIDR} -p tcp -dport 3000 -log nolog
IN ACCEPT -source ${LAN_CIDR} -p tcp -dport 9090 -log nolog
IN ACCEPT -source ${LAN_CIDR} -p tcp -dport 9093 -log nolog
IN ACCEPT -source ${TS_CIDR} -p tcp -dport 3000 -log nolog
IN ACCEPT -source ${LAN_CIDR} -p tcp -dport 22 -log nolog
EOF
fi

echo "[INFO] Wrote ${CT_FW}"
pve-firewall restart
echo "[INFO] pve-firewall restarted."
