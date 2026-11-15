# barely-ai-agent — vendored host config

Reference copies of units/scripts for Debian host **`barely-ai-agent`** (`172.16.0.105`): Qwen2.5-14B via llama.cpp (GPU `:8080`) + Kev-0.8B System One (CPU `:8009`).

Live state lives on the host under `/home/llama`, `/etc/systemd/system`, `/usr/local/sbin`. This tree is the lab-repo source of truth to reduce drift.

## Layout

| Path | Purpose |
|------|---------|
| `systemd/` | `llama-*.service`, `kev*.service` |
| `bin/` | `aictl`, `llamactl` (shim), env/bootstrap/run/wait helpers, `torch-cpu.constraints.txt` |
| `ssh/` | `99-papita-hardening.conf` (key-only, `AllowUsers root`) |
| `apt/` | `20auto-upgrades` |
| `fail2ban/` | `sshd.local` (sshd jail only; LAN ignored) |
| `docs/` | Kernel policy, host hardening, supply-chain pins |

**Secrets are not vendored.** On host: `/etc/llama/secrets/` (`llama.api-keys`, `kev.api-key` / `kev.env`).

## Ports / control

| Service | Port | User | CPUs | Control |
|---------|------|------|------|---------|
| Qwen (`llama-server`) | `8080` | `llama` | 0–5 | `aictl … qwen` |
| Kev | `8009` | `kev` | 6–7 | `aictl … kev` |

`llamactl` is a deprecated shim → `aictl` (qwen). Prefer `aictl`.

## Apply notes (manual)

1. Copy `bin/*` → `/home/llama/bin/` and `/usr/local/sbin/{aictl,llamactl}` as appropriate; `chown`/`chmod` to match host.
2. Install `systemd/*.service` → `/etc/systemd/system/`; `daemon-reload`; enable wanted units.
3. Install `ssh/`, `apt/`, `fail2ban/` drop-ins; reload `ssh` / restart `fail2ban`.
4. Create secrets under `/etc/llama/secrets` (mode `640`, group `ai`) before starting servers.

Do **not** add continuous health probes that compete with inference (operator policy).

## Pins (see `docs/SUPPLY_CHAIN.md`)

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
