#!/bin/bash

set -euo pipefail

# This script is used to perform a pre-shutdown procedure on the node.
# It is used to ensure that the node is in a safe state before shutdown.
# It is used to ensure that the node is in a safe state before shutdown.

# -----------------------------------------------------------------------------
# Set noout flag to true for ceph cluster
# -----------------------------------------------------------------------------
set_noout_flag() {
    echo "Setting noout flag to true for ceph cluster..."
    ceph osd set noout true
    echo "Noout flag set to true for ceph cluster."
    return 0
}

# -----------------------------------------------------------------------------
# Main function
# -----------------------------------------------------------------------------
main() {
    set_noout_flag
    return 0
}

main "$@"
