#!/bin/bash
# Per-node: corosync-qdevice client + softdog watchdog (HA fencing prerequisite).
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "[ERROR] Run as root." >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive

if ! dpkg -s corosync-qdevice >/dev/null 2>&1; then
    echo "[INFO] Installing corosync-qdevice..."
    apt-get update -qq
    apt-get install -y corosync-qdevice
fi

if ! grep -qxF 'softdog' /etc/modules 2>/dev/null; then
    echo 'softdog' >> /etc/modules
    echo "[INFO] Added softdog to /etc/modules."
fi

if ! lsmod | grep -q '^softdog'; then
    modprobe softdog || echo "[WARN] modprobe softdog failed; check kernel module availability."
fi

if [[ -e /dev/watchdog ]] || find /dev -maxdepth 1 -name 'watchdog*' -print -quit | grep -q .; then
    watchdog_devices="$(find /dev -maxdepth 1 -name 'watchdog*' -print 2>/dev/null | tr '\n' ' ')"
    echo "[INFO] Watchdog device present (${watchdog_devices})."
else
    echo "[WARN] No /dev/watchdog device; HA fencing may not work until softdog loads."
fi

if command -v systemctl >/dev/null 2>&1; then
    systemctl enable watchdog-mux 2>/dev/null || true
    if ! systemctl is-active watchdog-mux >/dev/null 2>&1; then
        systemctl start watchdog-mux 2>/dev/null || echo "[WARN] watchdog-mux not running; install pve-ha-manager or reboot."
    fi
    if systemctl is-active watchdog-mux >/dev/null 2>&1; then
        echo "[INFO] watchdog-mux active (HA fencing multiplexer)."
    fi
    systemctl is-enabled corosync-qdevice 2>/dev/null || true
fi

echo "[INFO] Node QDevice client + watchdog prep done on $(hostname -s)."
