#!/usr/bin/env bash
# Merge Qwen/Qwen3-14B + neoyipeng/FinSentQwen-14B (PEFT LoRA), export the
# 3x5120 sequence-classification score head, and build FinSentQwen-14B-Q4_K_M.gguf.
#
# Run on a build host with >=32 GB RAM (or on barely-ai-agent with services stopped
# and swap available) before switching llama-server to FinSentQwen-14B.
set -euo pipefail

BASE_MODEL="${FINSENT_BASE_MODEL:-Qwen/Qwen3-14B}"
BASE_REV="${FINSENT_BASE_REV:-40c069824f4251a91eefaf281ebe4c544efd3e18}"
ADAPTER_REPO="${FINSENT_ADAPTER_REPO:-neoyipeng/FinSentQwen-14B}"
ADAPTER_REV="${FINSENT_ADAPTER_REV:-main}"

LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-/home/llama/src/llama.cpp}"
MODELS_DIR="${MODELS_DIR:-/home/llama/models}"
WORK_DIR="${WORK_DIR:-/home/llama/models/.build-finsentqwen}"
PYTHON_BIN="${PYTHON_BIN:-/home/llama/kev/src/.venv/bin/python}"
QUANT_TYPE="${QUANT_TYPE:-Q4_K_M}"

export HF_HOME="${HF_HOME:-/home/llama/hf-cache}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-${HF_HOME}/huggingface}"

MERGED_DIR="${WORK_DIR}/merged-hf"
F16_GGUF="${WORK_DIR}/FinSentQwen-14B-f16.gguf"
OUT_GGUF="${MODELS_DIR}/FinSentQwen-14B-${QUANT_TYPE}.gguf"
OUT_HEAD_JSON="${MODELS_DIR}/finsentqwen-score-head.json"
OUT_HEAD_PT="${MODELS_DIR}/finsentqwen-score-head.pt"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -f "${LLAMA_CPP_DIR}/convert_hf_to_gguf.py" ]] || die "missing ${LLAMA_CPP_DIR}/convert_hf_to_gguf.py"
[[ -x "${LLAMA_CPP_DIR}/build/bin/llama-quantize" ]] || die "missing ${LLAMA_CPP_DIR}/build/bin/llama-quantize"
mkdir -p "${MODELS_DIR}" "${WORK_DIR}"

echo "[1/3] Merging ${BASE_MODEL}@${BASE_REV} + ${ADAPTER_REPO}@${ADAPTER_REV} and exporting score head"
"${PYTHON_BIN}" - "${BASE_MODEL}" "${BASE_REV}" "${ADAPTER_REPO}" "${ADAPTER_REV}" \
  "${MERGED_DIR}" "${OUT_HEAD_JSON}" "${OUT_HEAD_PT}" <<'PY'
import json
import sys
from pathlib import Path

import torch
from huggingface_hub import hf_hub_download
from peft import PeftModel
from transformers import AutoModelForSequenceClassification, AutoTokenizer

base_model, base_rev, adapter_repo, adapter_rev, merged_dir, out_json, out_pt = sys.argv[1:]

tok = AutoTokenizer.from_pretrained(base_model, revision=base_rev)
base = AutoModelForSequenceClassification.from_pretrained(
    base_model,
    revision=base_rev,
    num_labels=3,
    torch_dtype=torch.float16,
    low_cpu_mem_usage=True,
    device_map="cpu",
)
peft_model = PeftModel.from_pretrained(base, adapter_repo, revision=adapter_rev)
merged = peft_model.merge_and_unload()

score_weight = merged.score.weight.detach().float().cpu()
score_bias = (
    merged.score.bias.detach().float().cpu()
    if getattr(merged.score, "bias", None) is not None
    else None
)

thresholds = {}
try:
    thresh_path = hf_hub_download(repo_id=adapter_repo, filename="thresholds.json", revision=adapter_rev)
    thresholds = json.loads(Path(thresh_path).read_text(encoding="utf-8"))
except Exception:
    pass

torch.save(
    {
        "base_model": base_model,
        "base_revision": base_rev,
        "adapter_repo": adapter_repo,
        "adapter_revision": adapter_rev,
        "score_weight": score_weight,
        "score_bias": score_bias,
        "thresholds": thresholds,
    },
    out_pt,
)

head_payload = {
    "base_model": base_model,
    "base_revision": base_rev,
    "adapter_repo": adapter_repo,
    "adapter_revision": adapter_rev,
    "max_tokens": 1024,
    "aspects": [
        "financial performance",
        "demand and commercial traction",
        "operations, supply, and capacity",
        "outlook and expectations",
        "overall company sentiment",
    ],
    "classes": ["positive", "negative", "no signal"],
    "hidden_size": int(score_weight.shape[1]),
    "num_labels": int(score_weight.shape[0]),
    "score_weight": [[round(float(x), 8) for x in row] for row in score_weight.tolist()],
    "score_bias": [round(float(x), 8) for x in score_bias.tolist()] if score_bias is not None else None,
    "thresholds": thresholds,
}
Path(out_json).write_text(json.dumps(head_payload, indent=2) + "\n", encoding="utf-8")

# Save inner Qwen3Model backbone (architectures=["Qwen3Model"], without score.weight)
# so convert_hf_to_gguf.py maps all tensors cleanly as a Qwen3 embedding backbone.
merged.model.save_pretrained(merged_dir, safe_serialization=True)
tok.save_pretrained(merged_dir)
print(f"Saved merged Qwen3Model backbone -> {merged_dir} and score head -> {out_json}")
PY

echo "[2/3] Converting merged HF backbone to F16 GGUF"
"${PYTHON_BIN}" "${LLAMA_CPP_DIR}/convert_hf_to_gguf.py" \
  "${MERGED_DIR}" \
  --outfile "${F16_GGUF}" \
  --outtype f16

echo "[3/3] Quantizing F16 GGUF -> ${OUT_GGUF} (${QUANT_TYPE})"
"${LLAMA_CPP_DIR}/build/bin/llama-quantize" "${F16_GGUF}" "${OUT_GGUF}" "${QUANT_TYPE}"
rm -rf "${F16_GGUF}" "${MERGED_DIR}"
rmdir "${WORK_DIR}" 2>/dev/null || true
chown llama:ai "${OUT_GGUF}" "${OUT_HEAD_JSON}" "${OUT_HEAD_PT}" 2>/dev/null || true

echo "=== Build complete ==="
echo "GGUF:       ${OUT_GGUF}"
echo "Score head: ${OUT_HEAD_JSON}"
