#!/usr/bin/env bash
# chrony for unprivileged Debian LXC: track NTP offset only (chronyd -x).
# CTs inherit the host clock; do not use makestep/rtcsync here (adjtimex fails in CT).
#
# Run inside the container as root, e.g. after apt install chrony:
#   pct push <vmid> deploy/setup/misc/lxc/papita-chrony-lxc.sh /root/papita-chrony-lxc.sh
#   pct exec <vmid> -- bash /root/papita-chrony-lxc.sh
#
# Optional env file (same directory name on the CT):
#   export $(grep -v '^#' /root/chrony-lxc.env | xargs) && bash /root/papita-chrony-lxc.sh
set -euo pipefail

NTP_SERVERS="${PAPITA_NTP_SERVERS:-pool.ntp.org}"
CONF_DROP="/etc/chrony/chrony.conf.d/99-papita-lxc-ntp.conf"
CHRONY_DEFAULT="/etc/default/chrony"

if [[ "${PAPITA_CHRONY_LXC_DISABLE:-0}" == "1" ]]; then
    if command -v systemctl >/dev/null 2>&1; then
        systemctl disable --now chrony.service 2>/dev/null || true
    fi
    echo "[INFO] chrony disabled; using Proxmox host system clock."
    date
    exit 0
fi

if ! command -v apt-get >/dev/null 2>&1; then
    echo "[ERROR] apt-get not found; is this a Debian-based CT?"
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get install -y chrony

install -d -m 0755 /etc/chrony/chrony.conf.d
{
    echo "# Papita LXC chrony (client-only; no clock control — see papita-chrony-lxc.sh)"
    for srv in ${NTP_SERVERS}; do
        echo "pool ${srv} iburst"
    done
    echo "# Do not add makestep or rtcsync in LXC (adjtimex: Operation not permitted)."
} >"${CONF_DROP}"

if [[ -f "${CHRONY_DEFAULT}" ]]; then
    if grep -q '^DAEMON_OPTS=' "${CHRONY_DEFAULT}"; then
        sed -i 's/^DAEMON_OPTS=.*/DAEMON_OPTS="-F 1 -x"/' "${CHRONY_DEFAULT}"
    else
        echo 'DAEMON_OPTS="-F 1 -x"' >>"${CHRONY_DEFAULT}"
    fi
else
    echo 'DAEMON_OPTS="-F 1 -x"' >"${CHRONY_DEFAULT}"
fi

systemctl enable chrony.service
systemctl restart chrony.service

if command -v chronyc >/dev/null 2>&1; then
    echo "[INFO] chrony tracking (offset only; clock owned by PVE host):"
    chronyc tracking 2>/dev/null | head -n 8 || true
fi
echo "[INFO] chrony LXC client configured. NTP servers: ${NTP_SERVERS}"
