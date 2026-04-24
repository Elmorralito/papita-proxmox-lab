#!/bin/bash

set -euo pipefail

# Pre-shutdown hook (systemd ExecStop): set Ceph OSD noout before power-off/reboot so OSDs
# are not marked out while the node is down. Paired with post-startup-proc.sh (ceph osd unset noout).

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
    set_noout_flag
    return 0
}

main "$@"
