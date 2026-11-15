# VRAM policy (P1)

GPU: GTX 1050 **4096 MiB**. Configured for `FinSentQwen-14B-Q4_K_M.gguf` (`Qwen3-14B` 40 layers @ ~200 MiB/layer: `-ngl 14`, `ctx 1024`, `ubatch 1024`, `--embedding --pooling none`, `threads 4`, ~3875 MiB VRAM used).

| Knob | Current | Rule |
|------|---------|------|
| `LLAMA_NGL` | 14 | Ceiling for 40-layer Qwen3-14B Q4_K_M at `ctx=1024, ubatch=1024, pooling=none` (which allocates a 673 MiB per-token output buffer) on 4GB |
| `LLAMA_CTX` | 1024 | Matches `FinSentQwen-14B` `MAX_TOKENS=1024` ceiling |
| `LLAMA_UBATCH` | 1024 | Matches `LLAMA_BATCH=1024` so a full 1024-token slice evaluates in one single forward pass |
| `LLAMA_THREADS` | 4 | Matches the 4 physical FMA cores of the `i7-7700HQ` (`85.06 t/s` vs `84.56 t/s` at 5 threads) |
| Kev | CPU only | Never share GPU with llama-server |

Dual-stack memory: llama `MemoryMax=22G`, Kev `MemoryMax=6G`.
