#!/usr/bin/env bash
# Apply in-cluster metric collectors (kube-state-metrics, node-exporter, Prometheus SA).
# Requires kubectl pointed at k8s-oldtimers. Does not create or print tokens.
set -euo pipefail

SCRIPT_DIR="$(dirname "$(realpath "$0")")"
KDIR="${SCRIPT_DIR}/kubernetes"

if ! command -v kubectl >/dev/null 2>&1; then
    echo "[ERROR] kubectl not found." >&2
    exit 1
fi

kubectl apply -f "${KDIR}/00-namespace.yaml"
kubectl apply -f "${KDIR}/prometheus-external-rbac.yaml"
kubectl apply -f "${KDIR}/kube-state-metrics.yaml"
kubectl apply -f "${KDIR}/node-exporter.yaml"
kubectl -n monitoring rollout status deploy/kube-state-metrics --timeout=180s
kubectl -n monitoring rollout status ds/node-exporter --timeout=180s
echo "[INFO] applied kubernetes metric collectors (no tokens written)."
