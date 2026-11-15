#!/usr/bin/env bash
set -euo pipefail
LOG=${KEV_LOG:-/home/llama/logs/kev-bootstrap.log}
mkdir -p "$(dirname "$LOG")" /home/llama/hf-cache /home/llama/kev/uv-cache
exec > >(tee -a "$LOG") 2>&1
echo "=== kev-bootstrap $(date -Is) ==="
# shellcheck disable=SC1091
source /home/llama/bin/kev-env
export PATH="/root/.local/bin:${PATH}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/home/llama/kev/uv-cache}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/home/llama/kev/uv-python}"
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"
export HF_HOME="${HF_HOME:-/home/llama/hf-cache}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-/home/llama/hf-cache/huggingface}"

GIT=(git -c "safe.directory=${KEV_SRC}")
cd "${KEV_SRC}"

if [[ -n "${KEV_GIT_SHA:-}" ]]; then
  cur=$("${GIT[@]}" rev-parse HEAD)
  if [[ "$cur" != "$KEV_GIT_SHA" ]]; then
    if [[ "${KEV_BOOTSTRAP_OFFLINE:-1}" == "1" ]]; then
      echo "ERROR: Kev src at $cur != pinned $KEV_GIT_SHA and offline mode forbids fetch" >&2
      exit 1
    fi
    "${GIT[@]}" fetch --depth 1 origin "${KEV_GIT_SHA}"
    "${GIT[@]}" checkout --detach "${KEV_GIT_SHA}"
  else
    echo "Kev git already pinned at ${KEV_GIT_SHA}"
  fi
fi

PYBIN=/home/llama/kev/uv-python/cpython-3.13.18-linux-x86_64-gnu/bin/python3.13
if [[ ! -x .venv/bin/python ]]; then
  if [[ "${KEV_BOOTSTRAP_OFFLINE:-1}" == "1" ]]; then
    echo "ERROR: missing .venv and offline bootstrap" >&2
    exit 1
  fi
  uv sync --extra serve --python "$PYBIN"
fi

need_torch=0
if ! .venv/bin/python - <<'PY'
import torch, sys
sys.exit(0 if (not torch.cuda.is_available() and "cpu" in torch.__version__) else 1)
PY
then
  need_torch=1
fi
if [[ "$need_torch" == "1" ]]; then
  if [[ "${KEV_BOOTSTRAP_OFFLINE:-1}" == "1" ]]; then
    echo "ERROR: CUDA/non-CPU torch present and offline forbids reinstall" >&2
    exit 1
  fi
  uv pip install --python .venv/bin/python \
    --index-url https://download.pytorch.org/whl/cpu \
    -c /home/llama/kev/torch-cpu.constraints.txt \
    'torch==2.8.0'
fi

.venv/bin/python - <<'PY'
import os
from pathlib import Path
from huggingface_hub import snapshot_download

run = os.environ.get("KEV_RUN", "jaredpalmer/kev-0.8b@v1.0")
repo, _, rev = run.partition("@")
rev = os.environ.get("KEV_HF_REVISION") or (rev or None)
base = os.environ.get("KEV_BASE_MODEL", "Qwen/Qwen3.5-0.8B-Base")
offline = os.environ.get("KEV_BOOTSTRAP_OFFLINE", "1") == "1"
cache = Path(os.environ.get("HUGGINGFACE_HUB_CACHE", os.path.expanduser("~/.cache/huggingface/hub")))

def hub_dir(name: str) -> Path:
    return cache / ("models--" + name.replace("/", "--"))

def has_snapshot(name: str) -> bool:
    d = hub_dir(name)
    return d.is_dir() and any(d.glob("snapshots/*"))

for name, revision in ((repo, rev), (base, None)):
    if has_snapshot(name):
        print(f"cache hit {name} — skip download")
        continue
    if offline:
        raise SystemExit(f"ERROR: missing HF cache for {name} and KEV_BOOTSTRAP_OFFLINE=1")
    print(f"prefetch {name} rev={revision}")
    snapshot_download(name, revision=revision)

Path("/home/llama/kev/.seeded").write_text("ok\n")
print("prefetch done (offline-ready)")
PY

chown -R kev:ai /home/llama/hf-cache /home/llama/kev/uv-cache /home/llama/kev/uv-python /home/llama/kev/src/.venv /home/llama/kev/.seeded 2>/dev/null || true
echo "KEV bootstrap OK sha=${KEV_GIT_SHA:-?} run=${KEV_RUN} device=${KEV_DEVICE} port=${KEV_PORT} offline=${KEV_BOOTSTRAP_OFFLINE:-1}"
