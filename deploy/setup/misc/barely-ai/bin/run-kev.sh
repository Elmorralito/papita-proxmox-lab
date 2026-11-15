#!/usr/bin/env bash
set -euo pipefail
# shellcheck disable=SC1091
source /home/llama/bin/kev-env
export OMP_NUM_THREADS MKL_NUM_THREADS OPENBLAS_NUM_THREADS TORCH_NUM_THREADS
export KEV_DTYPE
export HF_HOME="${HF_HOME:-/home/llama/hf-cache}"
export TRANSFORMERS_CACHE="${HF_HOME}/huggingface"
export HUGGINGFACE_HUB_CACHE="${HF_HOME}/huggingface"
cd "${KEV_SRC}"
exec "${KEV_SRC}/.venv/bin/python" -m kev.serve \
  --run "${KEV_RUN}" \
  --host "${KEV_HOST}" \
  --port "${KEV_PORT}" \
  --device "${KEV_DEVICE}"
