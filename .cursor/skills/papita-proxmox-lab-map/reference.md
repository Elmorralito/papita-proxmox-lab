# papita-proxmox-lab — Complete File Inventory

Last aligned to repo tree (~46 tracked files). Gitignored paths listed separately.

---

## Root

| File                      | Role                                                                                      |
| ------------------------- | ----------------------------------------------------------------------------------------- |
| `README.md`               | Project title; links to network diagram and `docs/TIPSNTRICKS.md`                         |
| `LICENSE`                 | License text                                                                              |
| `pyproject.toml`          | Poetry config (`package-mode=false`); black/isort/flake8/mypy/pylint/interrogate settings |
| `poetry.lock`             | Locked dev deps (gitignored — regenerate locally)                                         |
| `.python-version`         | Python version pin (3.14)                                                                 |
| `.pre-commit-config.yaml` | Hooks: trailing-ws, yaml/toml, shellcheck, isort, black, flake8, pylint, mypy             |
| `.gitignore`              | Terraform state, `*.tfvars`, `.env`, `.terraform/`, `poetry.lock`, drawio backups         |

---

## `.cursor/` — Cursor agent config

| File                                                 | Role                                                  |
| ---------------------------------------------------- | ----------------------------------------------------- |
| `.cursor/rules/repo-map.mdc`                         | Always-on repo identity, tree, workflows, conventions |
| `.cursor/skills/papita-proxmox-lab-map/SKILL.md`     | On-demand deep map skill (this skill)                 |
| `.cursor/skills/papita-proxmox-lab-map/reference.md` | Full file inventory (this file)                       |

---

## `deploy/` — Orchestration (run from repo root)

| File                       | Role                                                                                   |
| -------------------------- | -------------------------------------------------------------------------------------- |
| `toolkit.sh`               | Main CLI: `build`, `devsync`, `test`, `proxmox`, `terraform`, AWS auth, pre-commit     |
| `proxmox.sh`               | SSH to PVE: `setup-node`, `get-temp`, `start-cluster`, `stop-cluster`, node discovery  |
| `terraform.sh`             | Terraform wrapper: init → workspace → plan\|apply\|destroy                             |
| `utils.sh`                 | Shared helpers: `log`, prompts, `run_command`, `aws_sso_login`, `aws_mfa_login`        |
| `usage.sh`                 | Help text: `usage_toolkit`, `usage_proxmox`, `usage_terraform`, `usage_setup_pve_node` |
| `setup-pve-node.usage.txt` | Manual shown via `less` during PVE setup prompts                                       |

### `toolkit.sh` functions

`build`, `devsync`, `run_pytest`, `deploy_proxmox`, `deploy_terraform`, `pre_commit`, `aws_cli`

### `proxmox.sh` functions

`setup_node`, `get_cluster_nodes`, `get_local_node`, `start_cluster`, `stop_cluster`, `get_cluster_temperature`, SSH helpers (`_pve_ssh_capture`, `_pve_cluster_for_each_remote_ssh`, `_pve_print_sensors_table`)

### `terraform.sh` functions

`run_terraform` — reads env tfvars, manages workspace, runs plan/apply/destroy

---

## `src/bash/` — PVE node scripts (SCP'd to `/root/deploy`)

| File                        | Role                                                                               |
| --------------------------- | ---------------------------------------------------------------------------------- |
| `setup-pve-node.sh`         | Interactive 11-step PVE bootstrap (APT, WoL, Tailscale, systemd, UI lockdown, TLS) |
| `post-startup-proc.sh`      | Boot hook: ceph noout unset, WoL peers from main node                              |
| `pre-shutdown-proc.sh`      | Shutdown hook: ceph osd set noout                                                  |
| `post-startup-proc.service` | systemd unit for post-startup hook                                                 |
| `pre-shutdown-proc.service` | systemd unit for pre-shutdown hook                                                 |
| `apt-dependencies.list`     | APT packages installed during step 1                                               |

### `src/bash/misc/tailscale/`

| File                    | Role                                               |
| ----------------------- | -------------------------------------------------- |
| `default.tags.list`     | Tailscale ACL tags (e.g. `tag:private-node`)       |
| `default.gateways.list` | Subnet routes advertised (default `100.64.0.0/10`) |

---

## `terraform/` — Infrastructure as code

### `terraform/environments/` (NOT in git)

| File                 | Role                                            |
| -------------------- | ----------------------------------------------- |
| `config.dev.tfvars`  | Dev env: owner, region, S3 backend, plan params |
| `config.prod.tfvars` | Prod env config                                 |
| `config.poc.tfvars`  | POC env config                                  |

### `terraform/plans/` — Root module

| File                  | Role                                                                                                      |
| --------------------- | --------------------------------------------------------------------------------------------------------- |
| `main.tf`             | S3 backend; wires `hybrid_proxmox_aws_cluster` module; default EFS/VPC params in locals                   |
| `variables.tf`        | `environment` (dev\|prod\|poc), `owner`, `aws_profile`, `aws_region`, `plan_specific_aws_security_params` |
| `README.md`           | Plans module docs                                                                                         |
| `.terraform.lock.hcl` | Provider version lock                                                                                     |

### `terraform/plans/hybrid_proxmox_aws_cluster/` — Hybrid module

| File                  | Role                                                                            |
| --------------------- | ------------------------------------------------------------------------------- |
| `main.tf`             | AWS + Tailscale providers; delegates to `aws/` submodule                        |
| `variables.tf`        | Module inputs: region, VPC, EFS, Tailscale, KMS                                 |
| `locals.tf`           | `resource_basename = "{plan_version}-{owner}-{project}-{environment}-{region}"` |
| `README.md`           | Module docs                                                                     |
| `.terraform.lock.hcl` | Provider lock                                                                   |

### `terraform/plans/hybrid_proxmox_aws_cluster/aws/` — AWS resources

| File                  | Role                                                                     |
| --------------------- | ------------------------------------------------------------------------ |
| `main.tf`             | Provider requirements only                                               |
| `network.tf`          | Optional VPC/subnets; EFS security group (port 2049 from Tailscale CIDR) |
| `efs.tf`              | Encrypted EFS, access point at `/pve`, KMS optional, lifecycle/backup    |
| `iam.tf`              | Tailscale router EC2 IAM role (SSM only)                                 |
| `variables.tf`        | AWS submodule inputs                                                     |
| `locals.tf`           | Submodule-local computed values                                          |
| `outputs.tf`          | Exported values (EFS ID, mount targets, etc.)                            |
| `README.md`           | AWS submodule docs                                                       |
| `.terraform.lock.hcl` | Provider lock                                                            |

### `terraform/plans/hybrid_proxmox_aws_cluster/tailscale/` — Placeholder

| File           | Role                                          |
| -------------- | --------------------------------------------- |
| `variables.tf` | Tailscale module variables (no resources yet) |
| `README.md`    | Placeholder docs                              |

### Terraform providers (all modules)

| Provider  | Version  |
| --------- | -------- |
| aws       | ~> 5.28  |
| tailscale | ~> 0.13  |
| archive   | ~> 2.7.0 |
| null      | ~> 3.2.3 |
| external  | ~> 2.3.5 |
| local     | ~> 2.5.3 |
| random    | ~> 3.8.1 |

Terraform version: `>=1.6.5, <2.0.0`

---

## `docs/` — Documentation

| File              | Role                                    |
| ----------------- | --------------------------------------- |
| `TIPSNTRICKS.md`  | Ceph, OSD, cluster maintenance runbooks |
| `Diagrams.drawio` | Network/architecture diagram (editable) |

Referenced in README but may be exported separately: `docs/Diagrams-Network.png`

---

## `rules-tmp/` — Draft Cursor rules (not active)

| File                  | Role                          |
| --------------------- | ----------------------------- |
| `bash_deploy.mdc`     | Draft bash deploy conventions |
| `terraform_style.mdc` | Draft Terraform style guide   |

Active rules live in `.cursor/rules/`.

---

## Referenced but absent from repo

| Path                              | Expected role                               |
| --------------------------------- | ------------------------------------------- |
| `libs/`                           | Python packages built by `toolkit.sh build` |
| `tests/`                          | pytest suite run by `toolkit.sh test`       |
| `dist/`                           | Built wheels output (generated)             |
| `.venv/`                          | Poetry virtualenv (generated, in-project)   |
| `terraform/environments/*.tfvars` | Local secrets and backend config            |

---

## Configuration cross-reference

| Concern                   | Primary file(s)                                               |
| ------------------------- | ------------------------------------------------------------- |
| Python lint/format        | `pyproject.toml`, `.pre-commit-config.yaml`                   |
| Git exclusions            | `.gitignore`                                                  |
| AWS/Terraform env         | `terraform/environments/config.<env>.tfvars` (local)          |
| EFS mount path            | `terraform/plans/main.tf` locals → default `/pve`             |
| Tailscale CIDR for EFS SG | `plan_specific_aws_security_params` → default `100.64.0.0/10` |
| PVE Tailscale tags/routes | `src/bash/misc/tailscale/default.*.list`                      |
| SSH to PVE                | `PAPITA_SSH_PASSWORD` env or SSH keys                         |
| AWS auth in toolkit       | `--aws-sso`, `--aws-mfa`, `--env-file`, `AWS_PROFILE`         |

---

## Pre-commit hooks (active)

| Hook                                                                               | Source                                |
| ---------------------------------------------------------------------------------- | ------------------------------------- |
| trailing-whitespace, end-of-file-fixer, check-yaml, check-toml, detect-private-key | pre-commit-hooks v5.0.0               |
| prettier (_.yaml, _.yml; excludes terraform/)                                      | mirrors-prettier                      |
| shellcheck                                                                         | shellcheck-precommit v0.10.0          |
| isort                                                                              | pycqa/isort 6.0.1                     |
| black                                                                              | psf/black 25.1.0                      |
| flake8                                                                             | pycqa/flake8 7.1.2                    |
| pylint                                                                             | local (system, pyproject.toml rcfile) |
| mypy                                                                               | mirrors-mypy v1.15.0                  |

Commented out: terraform_fmt/validate/docs, check-unused-vars, yamllint, interrogate.
