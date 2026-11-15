# Snapshots (HDD `/dev/sda`)

- Mount: `/mnt/ai-snapshots` (label `ai-snapshots`, ~931G)
- Script: `/usr/local/sbin/papita-ai-snapshot.sh` (`daily`|`weekly`)
- Timers: `papita-ai-snapshot-daily.timer` (04:40), `papita-ai-snapshot-weekly.timer` (Sun 05:10)
- Retention: 7 daily + 4 weekly; rsync hardlinks (`--link-dest`)
- Includes: models, hf-cache, bins/docs, kev src (no venv), `/etc/llama`, units, nftables, SSH/fail2ban hardening
- Excludes: `.venv`, uv caches, llama.cpp `build/`, logs
- Scheduling: `Nice=19`, `IOSchedulingClass=idle` (avoids competing with inference)

Manual: `systemctl start papita-ai-snapshot@daily.service`
