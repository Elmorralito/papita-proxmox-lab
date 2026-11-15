#!/usr/bin/env bash
set -euo pipefail
# shellcheck disable=SC1091
source /home/llama/bin/llama-env
url=${LLAMA_HEALTH_URL}
timeout=${LLAMA_HEALTH_TIMEOUT_SEC:-180}
key=""
if [[ -f "${LLAMA_API_KEY_FILE:-}" ]]; then
  key=$(head -n1 "${LLAMA_API_KEY_FILE}")
fi
auth=()
[[ -n "$key" ]] && auth=(-H "Authorization: Bearer ${key}")
deadline=$((SECONDS + timeout))
echo "waiting for ${url} (timeout=${timeout}s) MAINPID=${MAINPID:-none}"
while (( SECONDS < deadline )); do
  if [[ -n "${MAINPID:-}" ]] && ! kill -0 "${MAINPID}" 2>/dev/null; then
    echo "ERROR: llama-server main pid ${MAINPID} exited while waiting for health" >&2
    exit 1
  fi
  # /health may be open; also verify authenticated models endpoint
  if curl -fsS --max-time 2 "${auth[@]}" "$url" >/dev/null 2>&1; then
    if curl -fsS --max-time 2 "${auth[@]}" "http://127.0.0.1:${LLAMA_PORT}/v1/models" >/dev/null 2>&1; then
      echo "healthy+auth ok"
      exit 0
    fi
  fi
  sleep 2
done
echo "ERROR: health check timed out after ${timeout}s" >&2
exit 1
