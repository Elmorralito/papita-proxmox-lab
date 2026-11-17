#!/usr/bin/env bash
set -euo pipefail
# shellcheck disable=SC1091
source /home/llama/bin/llama-env
extra=()
if [[ -n "${LLAMA_API_KEY_FILE:-}" && -f "${LLAMA_API_KEY_FILE}" ]]; then
  extra+=(--api-key-file "${LLAMA_API_KEY_FILE}")
fi
if [[ -n "${LLAMA_CORS_ORIGINS:-}" ]]; then
  extra+=(--cors-origins "${LLAMA_CORS_ORIGINS}")
fi
if [[ "${LLAMA_WEBUI:-1}" == "0" ]]; then
  extra+=(--no-ui)
fi
if [[ "${LLAMA_EMBEDDING:-0}" == "1" ]]; then
  extra+=(--embedding)
fi
if [[ -n "${LLAMA_POOLING:-}" ]]; then
  extra+=(--pooling "${LLAMA_POOLING}")
fi
if [[ -n "${LLAMA_EMBD_NORMALIZE:-}" ]]; then
  extra+=(--embd-normalize "${LLAMA_EMBD_NORMALIZE}")
fi
exec "${LLAMA_BIN}" \
  -m "${LLAMA_MODEL}" \
  --alias "${LLAMA_ALIAS}" \
  --host "${LLAMA_HOST}" --port "${LLAMA_PORT}" \
  -c "${LLAMA_CTX}" \
  -ngl "${LLAMA_NGL}" \
  -t "${LLAMA_THREADS}" \
  -tb "${LLAMA_THREADS}" \
  -b "${LLAMA_BATCH}" \
  -ub "${LLAMA_UBATCH}" \
  -np "${LLAMA_PARALLEL}" \
  --load-mode mmap+mlock \
  --fit off \
  -cb \
  --metrics \
  "${extra[@]}"
