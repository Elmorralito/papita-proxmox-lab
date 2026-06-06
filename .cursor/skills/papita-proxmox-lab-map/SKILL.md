---
name: papita-proxmox-lab-map
description: >-
  Acknowledges papita-proxmox-lab identity and provides a detailed map of every
  component, file, and configuration. Use when onboarding to this repo, exploring
  architecture, locating config, planning changes, or when the user asks about
  repo structure, file layout, workflows, Terraform modules, deploy scripts, or
  PVE setup.
---

# papita-proxmox-lab — Repository Map

## Repo identity

**papita-proxmox-lab** is a hybrid **Proxmox VE cluster + AWS** lab. On-prem PVE nodes reach AWS shared storage (EFS) over **Tailscale**. Bash deploy scripts orchestrate node setup and Terraform; Python tooling is dev-only (Poetry + pre-commit).

Always-on summary lives in `.cursor/rules/repo-map.mdc`. This skill adds the full inventory and exploration workflow.

## When to use this skill

- First task in a session — acknowledge repo context before editing
- User asks "where is X?", "how does Y work?", or "what does this repo contain?"
- Planning changes across deploy, Terraform, or PVE bootstrap layers
- Refreshing the map after structural repo changes

## Acknowledgment checklist

Before making changes, confirm you understand:

```
Repo context:
- [ ] Hybrid Proxmox + AWS over Tailscale
- [ ] Entry CLI: deploy/toolkit.sh (run from repo root)
- [ ] PVE scripts copied to /root/deploy on nodes (src/bash/ → deploy/ on node)
- [ ] PVE setup manual: deploy/data/setup-pve-node.usage.txt
- [ ] Terraform root: terraform/plans/main.tf (S3 backend)
- [ ] Secrets: *.tfvars, .env — never commit
- [ ] Python: dev tooling only (no app package yet)
```

## Architecture

```
Local workstation
  deploy/toolkit.sh ─┬─► deploy/proxmox.sh ──SSH──► PVE nodes (src/bash/setup-pve-node.sh)
                     └─► deploy/terraform.sh ──────► terraform/plans/ (S3 backend)
                                                          └─► hybrid_proxmox_aws_cluster
                                                                └─► aws/ (VPC, EFS, IAM)
```

## Exploration workflow

When you need to locate or understand a component:

1. **Check the inventory** — read [reference.md](reference.md) for every tracked file and config
2. **Identify the layer** — deploy orchestration | PVE bootstrap | Terraform | dev tooling | docs
3. **Read the entrypoint** — don't start in submodules; follow the call chain:
   - `deploy/toolkit.sh` → `proxmox.sh` / `terraform.sh`
   - `terraform/plans/main.tf` → `hybrid_proxmox_aws_cluster/main.tf` → `aws/`
   - `deploy/proxmox.sh setup-node` → SCP `src/bash/`, `src/python/`, `utils.sh`, `usage.sh`, `data/setup-pve-node.usage.txt` → `bash setup-pve-node.sh`
4. **Check untracked config** — `terraform/environments/config.{dev|prod|poc}.tfvars`, `.env` (gitignored)
5. **Note absent dirs** — `libs/`, `tests/` referenced by toolkit but not yet in repo

## Key workflows (quick reference)

### Toolkit (`deploy/toolkit.sh`)

| Action                           | Purpose                             |
| -------------------------------- | ----------------------------------- |
| `build`                          | Build wheels from `libs/` → `dist/` |
| `devsync`                        | build + pip install wheels          |
| `test`                           | build + pytest with coverage        |
| `proxmox` / `deploy_proxmox`     | Delegate to `proxmox.sh`            |
| `terraform` / `deploy_terraform` | Delegate to `terraform.sh`          |

Required: `-e dev\|prod`. Optional: `--env-file`, AWS SSO/MFA, `--pre-commit`, action flags.

### Proxmox (`deploy/proxmox.sh`)

| Action                         | Purpose                                          |
| ------------------------------ | ------------------------------------------------ |
| `setup-node`                   | SCP `src/bash/` to node, run `setup-pve-node.sh` |
| `get-temp`                     | Cluster temperature via `sensors -j` (step 5)    |
| `start-cluster`                | WoL peer nodes via `pvenode wakeonlan`           |
| `stop-cluster`                 | Per-node `pvesh stopall` + hypervisor shutdown   |
| `cluster-nodes` / `local-node` | Discovery helpers                                |

SSH: ControlMaster multiplexing; password via `PAPITA_SSH_PASSWORD` or keys. **Must source `utils.sh` before calling `log`.**

### PVE setup (`setup-pve-node.sh`) — 17 steps

Controlled by `PVE_SETUP_LAST_STEP=17` and `_skip_pve_step` when jumping via menu.

| #   | Step                          | Notes                                                                 |
| --- | ----------------------------- | --------------------------------------------------------------------- |
| 1   | APT + deps + cron + microcode | `apt-dependencies.list`; exits on failure                             |
| 2   | Hibernate off                 | WoL-friendly poweroff                                                 |
| 3   | Wake-on-LAN                   |                                                                       |
| 4   | Locales                       |                                                                       |
| 5   | lm-sensors                    | Enables `proxmox.sh get-temp`                                         |
| 6   | chrony NTP                    | Configurable pool servers                                             |
| 7   | `/etc/hosts`                  | `src/python/misc/cluster/discover_hosts.py` — **before cluster join** |
| 8   | Tailscale setup               | sysctl, optional `cluster.fw`, optional NAT                           |
| 9   | `tailscale up`                | Optional sanity check 9.4                                             |
| 10  | Post-startup hook             | Quorum wait, ceph noout unset, main-node WoL                          |
| 11  | Pre-shutdown hook             | Optional stopall, ceph noout set                                      |
| 12  | Email                         | postfix + Proxmox mailto                                              |
| 13  | SMART monitoring              | Monthly cron                                                          |
| 14  | Enable cluster firewall       | `enable: 1` in `cluster.fw`                                           |
| 15  | Subscription nag              | proxmoxlib.js patch                                                   |
| 16  | vzdump backup cron            | Configurable schedule/storage                                         |
| 17  | Tailscale TLS :8006           | Main node only                                                        |

Manual: `deploy/data/setup-pve-node.usage.txt` (shown via `usage_setup_pve_node` in `deploy/usage.sh`).

### Terraform (`deploy/terraform.sh`)

Flow: `terraform/environments/config.<env>.tfvars` → `terraform init` (S3 backend) → workspace `<project>-<env>` → plan|apply|destroy.

Resource basename: `{plan_version}-{owner}-{project}-{environment}-{region}` (see `hybrid_proxmox_aws_cluster/locals.tf`).

## Agent conventions

- **Shell:** `set -euo pipefail`; source `deploy/utils.sh` + `deploy/usage.sh` before `log`; use `log INFO|WARN|ERROR`
- **Remote deploy path on PVE:** `/root/deploy` (contents of `src/bash/` plus copied `utils.sh`, `usage.sh`, `data/`)
- **Terraform edits:** under `terraform/plans/`; env values in untracked tfvars
- **Docs:** runbooks in `docs/TIPSNTRICKS.md`; diagram in `docs/Diagrams.drawio`
- **Adding a setup step:** bump `PVE_SETUP_LAST_STEP`, add `_skip_pve_step N`, update menu + `deploy/data/setup-pve-node.usage.txt`

## Refreshing the map

After adding/removing files or changing workflows:

1. Run `find . -type f -not -path './.git/*' -not -path './.venv/*' | sort` from repo root
2. Update [reference.md](reference.md) inventory
3. Update `.cursor/rules/repo-map.mdc` if architecture or workflows changed

## Additional resources

- Full file-by-file inventory: [reference.md](reference.md)
