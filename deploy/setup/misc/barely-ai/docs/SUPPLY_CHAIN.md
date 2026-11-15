# Supply chain pins (T1)

| Component | Pin |
|-----------|-----|
| FinSentQwen base (`Qwen/Qwen3-14B`) | `40c069824f4251a91eefaf281ebe4c544efd3e18` |
| FinSentQwen LoRA (`neoyipeng/FinSentQwen-14B`) | `main` (`r=16, alpha=32`, 3-class `score` head exported via `bin/finsentqwen-export-gguf.sh`) |
| `llama.cpp` | `956591f` + `patches/llama-server-output-indices.patch` |
| `sentencepiece` (in `/home/llama/kev/src/.venv`) | `0.2.3` (used by `convert_hf_to_gguf.py` during GGUF export) |
| Kev git | `2074cc44256200bb37540103fa4572901faa10f3` (`kev-1.0-23-g2074cc4`) |
| HF `jaredpalmer/kev-0.8b` | `bf75a6a8848ea6960ff2ed108d9ed44c2941174f` (tag v1.0) |
| Torch | `2.8.0+cpu` via `/home/llama/kev/torch-cpu.constraints.txt` |

`KEV_BOOTSTRAP_OFFLINE=1` (default): bootstrap refuses Hub/git/network if cache/venv/pin missing.
To reseed: `KEV_BOOTSTRAP_OFFLINE=0 systemctl start kev-bootstrap`.
