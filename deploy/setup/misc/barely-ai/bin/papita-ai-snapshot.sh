#!/usr/bin/env bash
# Periodic barely-ai-agent config+model snapshot → /mnt/ai-snapshots (HDD)
set -euo pipefail
SNAP_ROOT=${SNAP_ROOT:-/mnt/ai-snapshots/barely}
LOG=${SNAP_ROOT}/logs/snapshot.log
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
INTERVAL=${1:-daily}   # daily|weekly
KEEP_DAILY=${KEEP_DAILY:-7}
KEEP_WEEKLY=${KEEP_WEEKLY:-4}

mkdir -p "${SNAP_ROOT}/logs" "${SNAP_ROOT}/daily" "${SNAP_ROOT}/weekly"
exec >>"$LOG" 2>&1
echo "=== snapshot ${INTERVAL} ${STAMP} ==="

if ! mountpoint -q /mnt/ai-snapshots; then
  echo "ERROR: /mnt/ai-snapshots not mounted" >&2
  exit 1
fi

avail_k=$(df -Pk /mnt/ai-snapshots | awk 'NR==2{print $4}')
if [[ "$avail_k" -lt $((20*1024*1024)) ]]; then
  echo "ERROR: <20GiB free on snapshot volume (${avail_k} KiB)" >&2
  exit 1
fi

dest_base="${SNAP_ROOT}/${INTERVAL}"
work="${dest_base}/.partial-${STAMP}"
latest="${dest_base}/latest"
link_dest=()
if [[ -d "$latest" ]]; then
  link_dest=(--link-dest="$latest")
fi

mkdir -p "$work"
ionice -c3 -p $$ 2>/dev/null || true
renice +19 $$ >/dev/null 2>&1 || true

RSYNC=(rsync -aHAX --numeric-ids --info=stats2
  --exclude '.venv/'
  --exclude 'uv-cache/'
  --exclude 'uv-python/'
  --exclude 'ccache/'
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude 'logs/'
  --exclude 'build/'
)

mkdir -p "$work/home_llama/models" "$work/home_llama/hf-cache" "$work/home_llama/bin" \
  "$work/home_llama/docs" "$work/home_llama/kev"

"${RSYNC[@]}" "${link_dest[@]}" /home/llama/models/ "$work/home_llama/models/"
"${RSYNC[@]}" "${link_dest[@]}" /home/llama/hf-cache/ "$work/home_llama/hf-cache/"
"${RSYNC[@]}" "${link_dest[@]}" /home/llama/bin/ "$work/home_llama/bin/"
"${RSYNC[@]}" "${link_dest[@]}" /home/llama/docs/ "$work/home_llama/docs/"
[[ -f /home/llama/README.md ]] && cp -a /home/llama/README.md "$work/home_llama/"
# kev src without venv/caches
"${RSYNC[@]}" "${link_dest[@]}" \
  --exclude '.venv/' --exclude 'uv-cache/' --exclude 'uv-python/' \
  /home/llama/kev/src/ "$work/home_llama/kev/src/"
[[ -f /home/llama/kev/torch-cpu.constraints.txt ]] && \
  cp -a /home/llama/kev/torch-cpu.constraints.txt "$work/home_llama/kev/"
[[ -f /home/llama/kev/.seeded ]] && cp -a /home/llama/kev/.seeded "$work/home_llama/kev/"

mkdir -p "$work/etc/systemd/system" "$work/etc/ssh/sshd_config.d" \
  "$work/etc/fail2ban/jail.d" "$work/etc/apt/apt.conf.d" "$work/etc/default/grub.d"
"${RSYNC[@]}" /etc/llama/ "$work/etc/llama/"
cp -a /etc/nftables.conf "$work/etc/" 2>/dev/null || true
cp -a /etc/ssh/sshd_config.d/99-papita-hardening.conf "$work/etc/ssh/sshd_config.d/" 2>/dev/null || true
cp -a /etc/fail2ban/jail.d/sshd.local "$work/etc/fail2ban/jail.d/" 2>/dev/null || true
cp -a /etc/apt/apt.conf.d/20auto-upgrades "$work/etc/apt/apt.conf.d/" 2>/dev/null || true
cp -a /etc/systemd/system/llama-*.service /etc/systemd/system/kev*.service \
  "$work/etc/systemd/system/" 2>/dev/null || true
cp -a /etc/default/grub.d/99-llama-perf.cfg "$work/etc/default/grub.d/" 2>/dev/null || true

mkdir -p "$work/usr_local_sbin"
cp -a /usr/local/sbin/aictl /usr/local/sbin/llamactl /usr/local/sbin/ai-show-keys \
  /usr/local/sbin/papita-ai-snapshot.sh \
  "$work/usr_local_sbin/" 2>/dev/null || true

{
  echo "stamp=${STAMP}"
  echo "interval=${INTERVAL}"
  echo "host=$(hostname -f 2>/dev/null || hostname)"
  echo "--- llama-env ---"
  cat /home/llama/bin/llama-env
  echo "--- kev-env ---"
  cat /home/llama/bin/kev-env
} >"$work/MANIFEST.txt"
chmod -R go-rwx "$work/etc/llama" 2>/dev/null || true

final="${dest_base}/${STAMP}"
mv "$work" "$final"
ln -sfn "$final" "$latest"

keep=$KEEP_DAILY
[[ "$INTERVAL" == weekly ]] && keep=$KEEP_WEEKLY
mapfile -t old < <(ls -1dt "${dest_base}"/20* 2>/dev/null || true)
if ((${#old[@]} > keep)); then
  for d in "${old[@]:$keep}"; do
    echo "prune $d"
    rm -rf "$d"
  done
fi

df -h /mnt/ai-snapshots | tail -1
echo "OK ${final}"
