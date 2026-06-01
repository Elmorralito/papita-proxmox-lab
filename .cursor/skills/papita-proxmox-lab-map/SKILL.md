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
- [ ] PVE scripts copied to /root/deploy on nodes
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
   - `deploy/proxmox.sh setup-node` → SCP `src/bash/` → `setup-pve-node.sh`
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
| `get-temp`                     | Cluster temperature via `sensors -j`             |
| `start-cluster`                | WoL peer nodes via `pvenode wakeonlan`           |
| `stop-cluster`                 | Per-node `pvesh stopall` + hypervisor shutdown   |
| `cluster-nodes` / `local-node` | Discovery helpers                                |

SSH: ControlMaster multiplexing; password via `PAPITA_SSH_PASSWORD` or keys.

### PVE setup steps (`setup-pve-node.sh`)

1. APT → 2. Hibernate → 3. WoL → 4. Locales → 5–6. Tailscale → 7. Post-startup systemd → 8. Pre-shutdown systemd → 9. Remove subscription nag → 10. Restrict UI to Tailscale → 11. Tailscale TLS cert for :8006

### Terraform (`deploy/terraform.sh`)

Flow: `terraform/environments/config.<env>.tfvars` → `terraform init` (S3 backend) → workspace `<project>-<env>` → plan|apply|destroy.

Resource basename: `{plan_version}-{owner}-{project}-{environment}-{region}` (see `hybrid_proxmox_aws_cluster/locals.tf`).

## Agent conventions

- **Shell:** `set -euo pipefail`; source `deploy/utils.sh` + `deploy/usage.sh`; use `log INFO|WARN|ERROR`
- **Remote deploy path on PVE:** `/root/deploy`
- **Terraform edits:** under `terraform/plans/`; env values in untracked tfvars
- **Docs:** runbooks in `docs/TIPSNTRICKS.md`; diagram in `docs/Diagrams.drawio`

## Refreshing the map

After adding/removing files or changing workflows:

1. Run `find . -type f -not -path './.git/*' -not -path './.venv/*' | sort` from repo root
2. Update [reference.md](reference.md) inventory
3. Update `.cursor/rules/repo-map.mdc` if architecture or workflows changed

## Additional resources

- Full file-by-file inventory: [reference.md](reference.md)
