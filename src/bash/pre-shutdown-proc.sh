#!/bin/bash

set -euo pipefail

PAPITA_PRE_SHUTDOWN_DEFAULTS="/etc/default/papita-pre-shutdown"
STOPALL_TIMEOUT=120
ENABLE_STOPALL=1

# -----------------------------------------------------------------------------
# Gracefully stop guests before maintenance flags (optional)
# -----------------------------------------------------------------------------
stop_all_guests() {
    if [[ -f "$PAPITA_PRE_SHUTDOWN_DEFAULTS" ]]; then
        # shellcheck disable=SC1090
        source "$PAPITA_PRE_SHUTDOWN_DEFAULTS"
    fi
    if [[ "${ENABLE_STOPALL:-1}" != "1" ]]; then
        echo "INFO: Guest stopall disabled via ${PAPITA_PRE_SHUTDOWN_DEFAULTS}."
        return 0
    fi
    if ! command -v pvesh >/dev/null 2>&1; then
        echo "WARN: pvesh not found; skipping stopall."
        return 0
    fi
    echo "INFO: Stopping all VMs/containers (timeout ${STOPALL_TIMEOUT}s)..."
    if timeout "${STOPALL_TIMEOUT}" pvesh stopall --timeout "${STOPALL_TIMEOUT}" 2>/dev/null; then
        echo "INFO: pvesh stopall completed."
    else
        echo "WARN: pvesh stopall failed or timed out; continuing shutdown."
    fi
    return 0
}

# -----------------------------------------------------------------------------
# Ceph: set noout (paired with post-startup-proc.sh "ceph osd unset noout")
# -----------------------------------------------------------------------------
set_noout_flag() {
    if ! command -v ceph >/dev/null 2>&1; then
        echo "INFO: ceph not installed; skipping ceph osd set noout."
        return 0
    fi
    echo "INFO: Setting Ceph OSD noout before shutdown..."
    if ceph osd set noout; then
        echo "INFO: Ceph OSD noout set."
    else
        echo "WARN: Failed to set Ceph OSD noout (cluster down, no Ceph, or quorum loss); continuing shutdown."
    fi
    return 0
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
main() {
    stop_all_guests
    set_noout_flag
    return 0
}

main "$@"
