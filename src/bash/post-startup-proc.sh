#!/bin/bash

set -euo pipefail

# This script is used to perform a post-startup procedure on the node.
# It is used to ensure that the node is in a safe state after startup.
# It is used to ensure that the node is in a safe state after startup.

# -----------------------------------------------------------------------------
# Set noout flag to false for ceph cluster
# -----------------------------------------------------------------------------
set_noout_flag() {
    echo "INFO: Unsetting noout flag for ceph cluster..."
    ceph osd unset noout || {
        echo "ERROR: Failed to unset noout flag for ceph cluster. Continuing..."
        return 0
    }
    echo "INFO: Noout flag unset for ceph cluster."
    return 0
}

refresh_ceph_osd_nodes() {
    echo "INFO: Refreshing ceph OSD nodes..."
    sleep 5
    ceph osd tree || {
        echo "ERROR: Failed to refresh ceph OSD nodes. Continuing..."
        return 0
    }
    systemctl restart ceph-osd.target || {
        echo "ERROR: Failed to restart ceph-osd.target. Continuing..."
        return 0
    }
    sleep 5
    systemctl restart ceph-mgr.target || {
        echo "ERROR: Failed to restart ceph-mgr.target. Continuing..."
        return 0
    }
    sleep 5
    systemctl restart pvestatd.service || {
        echo "ERROR: Failed to restart pvestatd.service. Continuing..."
        return 0
    }
    sleep 5
    echo "INFO: Ceph OSD nodes refreshed."
    return 0
}

wake_on_lan_nodes() {
    if [ ! -f /etc/default/pve-main-node ]; then
        echo "INFO: Skipping wake-on-LAN nodes. /etc/default/pve-main-node not found."
        return 0
    fi
    main_node=$(cat /etc/default/pve-main-node)
    if [ "$HOSTNAME" != "$main_node" ]; then
        echo "INFO: Skipping wake-on-LAN nodes. $HOSTNAME is not the main node."
        return 0
    fi
    echo "INFO: Waking up on-LAN nodes..."
    if ! which jq &>/dev/null || ! which pvesh &>/dev/null || ! which pvenode &>/dev/null; then
        echo "ERROR: jq, pvesh, or pvenode not found. Skipping..."
        return 0
    fi
    nodes=$(pvesh get /cluster/resources --type node --output-format json | jq -r .[].node)
    for node in $nodes; do
        echo "INFO: Waking up $node..."
        if [ "$node" == "$HOSTNAME" ]; then
            echo "INFO: Skipping $node. It is the current node."
            continue
        fi
        pvenode wakeonlan "$node" || {
            echo "ERROR: Failed to wake up $node. Continuing..."
            continue
        }
    done
    echo "INFO: On-LAN nodes woken up."
    return 0
}

# -----------------------------------------------------------------------------
# Main function
# -----------------------------------------------------------------------------
main() {
    set_noout_flag
    refresh_ceph_osd_nodes
    wake_on_lan_nodes
    return 0
}

main "$@"
