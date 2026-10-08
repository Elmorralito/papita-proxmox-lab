#!/usr/bin/env bash
# Pin api.k8s.oldtimers.lab to the HA API VIP so kubelets can scrape/register without MagicDNS.
# Run inside each k8s VM (or via qm guest exec).
set -euo pipefail

VIP="${PAPITA_K8S_API_VIP:-172.16.30.10}"
NAME="${PAPITA_K8S_API_DNS:-api.k8s.oldtimers.lab}"
HOSTS="${PAPITA_HOSTS_FILE:-/etc/hosts}"

if grep -qE "[[:space:]]${NAME}([[:space:]]|$)" "$HOSTS"; then
    echo "[INFO] ${NAME} already present in ${HOSTS}"
    grep -E "[[:space:]]${NAME}([[:space:]]|$)" "$HOSTS"
    exit 0
fi

printf '%s\t%s\n' "$VIP" "$NAME" >>"$HOSTS"
echo "[INFO] appended ${VIP} ${NAME} to ${HOSTS}"
