#!/usr/bin/env bash
set -euo pipefail
# shellcheck disable=SC1091
source /home/llama/bin/kev-env
# shellcheck disable=SC1091
[[ -f /etc/llama/secrets/kev.env ]] && source /etc/llama/secrets/kev.env
url=${KEV_HEALTH_URL}
timeout=${KEV_HEALTH_TIMEOUT_SEC:-600}
auth=()
[[ -n "${KEV_API_KEY:-}" ]] && auth=(-H "Authorization: Bearer ${KEV_API_KEY}")
deadline=$((SECONDS + timeout))
echo "waiting for ${url} (timeout=${timeout}s) MAINPID=${MAINPID:-none}"
while (( SECONDS < deadline )); do
  if [[ -n "${MAINPID:-}" ]] && ! kill -0 "${MAINPID}" 2>/dev/null; then
    echo "ERROR: kev main pid exited" >&2
    exit 1
  fi
  if curl -fsS --max-time 3 "${auth[@]}" "$url" >/dev/null 2>&1; then
    echo "healthy+auth ok"
    exit 0
  fi
  sleep 3
done
echo "ERROR: kev health timed out" >&2
exit 1
