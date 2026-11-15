# Supply chain pins (T1)

| Component | Pin |
|-----------|-----|
| Kev git | `2074cc44256200bb37540103fa4572901faa10f3` (`kev-1.0-23-g2074cc4`) |
| HF `jaredpalmer/kev-0.8b` | `bf75a6a8848ea6960ff2ed108d9ed44c2941174f` (tag v1.0) |
| Torch | `2.8.0+cpu` via `/home/llama/kev/torch-cpu.constraints.txt` |

`KEV_BOOTSTRAP_OFFLINE=1` (default): bootstrap refuses Hub/git/network if cache/venv/pin missing.
To reseed: `KEV_BOOTSTRAP_OFFLINE=0 systemctl start kev-bootstrap`.
