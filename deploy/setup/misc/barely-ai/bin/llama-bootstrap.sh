#!/usr/bin/env bash
# Bring host into a known-good state for llama-server (idempotent).
set -euo pipefail
LOG=${LLAMA_LOG:-/home/llama/logs/bootstrap.log}
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "=== llama-bootstrap $(date -Is) pid=$$ ==="

# shellcheck disable=SC1091
source /home/llama/bin/llama-env

die() { echo "ERROR: $*" >&2; exit 1; }

echo "[1/5] CPU performance governor"
if command -v cpupower >/dev/null; then
  cpupower frequency-set -g performance >/dev/null || true
fi
for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
  echo performance >"$g" 2>/dev/null || true
done

echo "[2/5] Wait for NVIDIA"
deadline=$((SECONDS + 90))
until nvidia-smi -L >/dev/null 2>&1; do
  (( SECONDS < deadline )) || die "nvidia-smi not ready after 90s"
  sleep 2
done
nvidia-smi -pm 1 >/dev/null 2>&1 || true
# Mobile 1050 often rejects -ac/-pl; ignore
nvidia-smi -ac 3504,1911 >/dev/null 2>&1 || true

echo "[3/5] THP / swappiness (best-effort)"
echo always >/sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null || true
sysctl -q vm.swappiness=1 2>/dev/null || true

echo "[4/5] Validate artifacts"
[[ -x "${LLAMA_BIN}" ]] || die "missing binary: ${LLAMA_BIN}"
[[ -f "${LLAMA_MODEL}" ]] || die "missing model: ${LLAMA_MODEL}"
[[ -r /home/llama/bin/run-server.sh ]] || die "missing run-server.sh"

echo "[5/5] Bootstrap OK"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || true
echo "model=$(basename "$LLAMA_MODEL") ngl=${LLAMA_NGL} ctx=${LLAMA_CTX} port=${LLAMA_PORT}"
