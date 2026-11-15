# VRAM policy (P1)

GPU: GTX 1050 **4096 MiB**. Observed: ~3883 MiB used with Qwen2.5-14B Q4_K_M, `-ngl 19`, `ctx 4096`.

| Knob | Current | Rule |
|------|---------|------|
| `LLAMA_NGL` | 19 | Ceiling for this GGUF on 4GB; raising needs lower ctx |
| `LLAMA_CTX` | 4096 | Cap; prefer drop to 2048 before lowering ngl |
| Kev | CPU only | Never share GPU with llama-server |

Dual-stack memory: llama `MemoryMax=22G`, Kev `MemoryMax=6G`.
