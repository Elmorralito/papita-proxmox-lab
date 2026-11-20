#!/usr/bin/env bash
# Harden Intel e1000e NICs against "Detected Hardware Unit Hang" → lost NFS/corosync → HA softdog reboot.
# Safe to re-run. Applies runtime settings, persists via /etc/network/interfaces post-up + systemd oneshot,
# and ensures GRUB has pcie_aspm=off (next reboot).
set -euo pipefail

IFACE="${1:-nic0}"
SERVICE_NAME="papita-e1000e-harden.service"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}"

_log() { printf '[%s] %s\n' "$1" "$2"; }

if [[ ! -d "/sys/class/net/${IFACE}" ]]; then
    _log ERROR "Interface ${IFACE} not found."
    exit 1
fi

driver="$(basename "$(readlink -f "/sys/class/net/${IFACE}/device/driver" 2>/dev/null || true)" 2>/dev/null || true)"
if [[ "${driver}" != "e1000e" ]]; then
    _log WARN "Driver on ${IFACE} is '${driver:-unknown}' (not e1000e); applying offload/EEE/ring hardening anyway."
fi

_apply_runtime() {
    ethtool -K "${IFACE}" tso off gso off gro off || true
    ethtool --set-eee "${IFACE}" eee off 2>/dev/null || true
    # Larger rings reduce TX descriptor stalls that precede e1000e unit hangs.
    ethtool -G "${IFACE}" rx 1024 tx 1024 2>/dev/null || ethtool -G "${IFACE}" rx 512 tx 512 2>/dev/null || true
}

_persist_interfaces() {
    local ifaces="/etc/network/interfaces"
    [[ -f "$ifaces" ]] || return 0
    python3 - "$IFACE" "$ifaces" <<'PY'
import sys
from pathlib import Path

iface, path = sys.argv[1], Path(sys.argv[2])
text = path.read_text()
post_up = (
    f"\tpost-up /usr/sbin/ethtool -K {iface} tso off gso off gro off; "
    f"/usr/sbin/ethtool --set-eee {iface} eee off || true; "
    f"/usr/sbin/ethtool -G {iface} rx 1024 tx 1024 || true\n"
)
comment = "\t# e1000e hang mitigation (Hardware Unit Hang → HA softdog reboot)\n"

# Upgrade an older minimal post-up line (keep a single comment).
old = f"\tpost-up /usr/sbin/ethtool -K {iface} tso off gso off gro off\n"
if old in text and f"ethtool --set-eee {iface}" not in text:
    text = text.replace(old, post_up, 1)
    if comment not in text:
        text = text.replace(f"iface {iface} inet manual\n", f"iface {iface} inet manual\n{comment}", 1)
    # Drop accidental duplicate comments from earlier runs.
    while comment + comment in text:
        text = text.replace(comment + comment, comment)
    path.write_text(text)
    raise SystemExit(0)

if f"ethtool -K {iface} tso off" in text:
    while comment + comment in text:
        text = text.replace(comment + comment, comment)
    if text != path.read_text():
        path.write_text(text)
    raise SystemExit(0)

needle = f"iface {iface} inet manual\n"
if needle not in text:
    print(f"[WARN] No 'iface {iface} inet manual' in {path}; relying on systemd unit only.", file=sys.stderr)
    raise SystemExit(0)

path.write_text(text.replace(needle, needle + comment + post_up, 1))
PY
}

_persist_systemd() {
    cat >"${UNIT_PATH}" <<EOF
[Unit]
Description=Papita e1000e hang mitigations (${IFACE})
Wants=network-online.target
After=network-online.target
Before=pve-ha-lrm.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/ethtool -K ${IFACE} tso off gso off gro off
ExecStart=-/usr/sbin/ethtool --set-eee ${IFACE} eee off
ExecStart=-/usr/sbin/ethtool -G ${IFACE} rx 1024 tx 1024

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now "${SERVICE_NAME}"
}

_ensure_pcie_aspm_off() {
    local grub="/etc/default/grub"
    [[ -f "$grub" ]] || return 0
    if grep -qE 'GRUB_CMDLINE_LINUX_DEFAULT=.*pcie_aspm=off' "$grub"; then
        _log INFO "GRUB already has pcie_aspm=off."
        return 0
    fi
    if grep -q '^GRUB_CMDLINE_LINUX_DEFAULT=' "$grub"; then
        sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 pcie_aspm=off"/' "$grub"
        # Collapse duplicate spaces / accidental double flags
        sed -i 's/pcie_aspm=off pcie_aspm=off/pcie_aspm=off/g' "$grub"
        sed -i 's/  */ /g' "$grub"
    else
        echo 'GRUB_CMDLINE_LINUX_DEFAULT="quiet pcie_aspm=off"' >>"$grub"
    fi
    if command -v update-grub >/dev/null 2>&1; then
        update-grub
        _log INFO "GRUB updated with pcie_aspm=off (takes effect on next reboot)."
    else
        _log WARN "update-grub missing; edit cmdline manually."
    fi
}

_apply_runtime
_persist_interfaces
_persist_systemd
_ensure_pcie_aspm_off

_log INFO "Runtime offloads:"
ethtool -k "${IFACE}" | egrep 'tcp-segmentation-offload|generic-segmentation-offload|generic-receive-offload' || true
_log INFO "EEE:"
ethtool --show-eee "${IFACE}" 2>/dev/null | head -3 || true
_log INFO "Rings:"
ethtool -g "${IFACE}" 2>/dev/null | egrep 'Current|RX:|TX:' | head -6 || true
_log INFO "Done (${IFACE})."
