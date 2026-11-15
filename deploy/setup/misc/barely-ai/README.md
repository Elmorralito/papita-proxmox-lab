# barely-ai-agent — vendored host config

Reference copies of units/scripts for Debian host **`barely-ai-agent`** (`172.16.0.105`): FinSentQwen-14B (`Qwen/Qwen3-14B` + `neoyipeng/FinSentQwen-14B` merged `Q4_K_M` + exported 3-class `score` head) via llama.cpp (GPU `:8080`, `--embedding --pooling none` + `output_indices` patch) + Kev-0.8B System One (CPU `:8009`).

Live state lives on the host under `/home/llama`, `/etc/systemd/system`, `/usr/local/sbin`. This tree is the lab-repo source of truth to reduce drift.

## Layout

| Path | Purpose |
|------|---------|
| `systemd/` | `llama-*.service`, `kev*.service` |
| `bin/` | `aictl`, `llamactl` (shim), `finsentqwen-export-gguf.sh`, env/bootstrap/run/wait helpers, `torch-cpu.constraints.txt` |
| `patches/` | `llama-server-output-indices.patch` (`output_indices` support on `/embedding` for single-pass 5-aspect extraction) |
| `ssh/` | `99-papita-hardening.conf` (key-only, `AllowUsers root`) |
| `apt/` | `20auto-upgrades` |
| `fail2ban/` | `sshd.local` (sshd jail only; LAN ignored) |
| `docs/` | Kernel policy, host hardening, supply-chain pins |

**Secrets are not vendored.** On host: `/etc/llama/secrets/` (`llama.api-keys`, `kev.api-key` / `kev.env`).

## Ports / control

| Service | Port | User | CPUs | Control |
|---------|------|------|------|---------|
| FinSentQwen-14B (`llama-server`) | `8080` | `llama` | 0–3 | `aictl … qwen` |
| Kev | `8009` | `kev` | 6–7 | `aictl … kev` |

`llamactl` is a deprecated shim → `aictl` (qwen). Prefer `aictl`.

## Apply notes (manual)

1. Copy `bin/*` → `/home/llama/bin/` and `/usr/local/sbin/{aictl,llamactl}` as appropriate; `chown`/`chmod` to match host.
2. When building `/home/llama/src/llama.cpp`, apply `patches/llama-server-output-indices.patch` (`git apply`) before building `llama-server`, and run `bin/finsentqwen-export-gguf.sh` to produce `/home/llama/models/FinSentQwen-14B-Q4_K_M.gguf` and `finsentqwen-score-head.{json,pt}`.
3. Install `systemd/*.service` → `/etc/systemd/system/`; run `systemctl daemon-reload`; enable wanted units.
4. Install `ssh/`, `apt/`, `fail2ban/` drop-ins; reload `ssh` / restart `fail2ban`.
5. Create secrets under `/etc/llama/secrets` (mode `640`, group `ai`) before starting servers.

Do **not** add continuous health probes that compete with inference (operator policy).

## Pins (see `docs/SUPPLY_CHAIN.md`)

- FinSentQwen-14B base (`Qwen/Qwen3-14B`): `40c069824f4251a91eefaf281ebe4c544efd3e18` + `neoyipeng/FinSentQwen-14B` LoRA (built via `bin/finsentqwen-export-gguf.sh` → `/home/llama/models/FinSentQwen-14B-Q4_K_M.gguf` + `/home/llama/models/finsentqwen-score-head.json`)
- Kev git: `2074cc44256200bb37540103fa4572901faa10f3`
- HF `jaredpalmer/kev-0.8b@v1.0`: `bf75a6a8848ea6960ff2ed108d9ed44c2941174f`
- Torch: `2.8.0+cpu` (`KEV_BOOTSTRAP_OFFLINE=1` after first seed)

## Snapshots

- Disk: `/dev/sda1` → `/mnt/ai-snapshots` (~916G)
- Timers: daily 04:40, weekly Sun 05:10 (`papita-ai-snapshot-*.timer`)
- Script: `bin/papita-ai-snapshot.sh` — see `docs/SNAPSHOTS.md`

## Network (LAN + Tailscale)

See `docs/NETWORK_ACCESS.md` and `nftables/nftables.conf`.
APIs `:8080`/`:8009` and SSH: `172.16.0.0/16` + `100.64.0.0/10` only. Outbound WAN allowed for maintenance.
OpenWrt: no WAN DNAT; `tailscale`↔`lan` forward; MCP agent installed (`wan_exposure=false`).
