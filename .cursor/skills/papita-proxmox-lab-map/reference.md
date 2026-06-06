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

| File                       | Role                                                                                                                                |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `toolkit.sh`               | Main CLI: `build`, `devsync`, `test`, `proxmox`, `terraform`, AWS auth, pre-commit                                                  |
| `proxmox.sh`               | SSH to PVE: `setup-node` (SCP `src/bash/`, `utils.sh`, `usage.sh`, `data/setup-pve-node.usage.txt`), `get-temp`, cluster start/stop |
| `terraform.sh`             | Terraform wrapper: init → workspace → plan\|apply\|destroy                                                                          |
| `utils.sh`                 | Shared helpers: `log`, `prompt_pve_start`, `prompt_until_*`, `prompt_crontab_schedule`, AWS auth, `run_command`                     |
| `usage.sh`                 | Help text: `usage_toolkit`, `usage_proxmox`, `usage_terraform`, `usage_setup_pve_node`                                              |
| `tailscale-pfsense-lan.sh` | Workstation helper: Tailscale ACL + pfSense LAN integration                                                                         |

### `deploy/data/`

| File                              | Role                                                 |
| --------------------------------- | ---------------------------------------------------- |
| `setup-pve-node.usage.txt`        | Full manual for 17-step PVE setup (shown via `less`) |
| `tailscale-pfsense-lan.usage.txt` | Usage for `tailscale-pfsense-lan.sh`                 |

### `toolkit.sh` functions

`build`, `devsync`, `run_pytest`, `deploy_proxmox`, `deploy_terraform`, `pre_commit`, `aws_cli`

### `proxmox.sh` functions

`setup_node`, `get_cluster_nodes`, `get_local_node`, `start_cluster`, `stop_cluster`, `get_cluster_temperature`, SSH helpers (`_pve_ssh_capture`, `_pve_cluster_for_each_remote_ssh`, `_pve_print_sensors_table`)

### `terraform.sh` functions

`run_terraform` — reads env tfvars, manages workspace, runs plan/apply/destroy

---

## `src/bash/` — PVE node scripts (SCP'd to `/root/deploy`)

| File                        | Role                                                                                        |
| --------------------------- | ------------------------------------------------------------------------------------------- |
| `setup-pve-node.sh`         | Interactive 17-step PVE bootstrap; `PVE_SETUP_LAST_STEP=17`, `_skip_pve_step`               |
| `post-startup-proc.sh`      | Boot: quorum wait (`/etc/default/papita-post-startup`), ceph noout unset, WoL               |
| `pre-shutdown-proc.sh`      | Shutdown: optional `pvesh stopall`, ceph osd set noout (`/etc/default/papita-pre-shutdown`) |
| `post-startup-proc.service` | systemd unit for post-startup hook                                                          |
| `pre-shutdown-proc.service` | systemd unit for pre-shutdown hook                                                          |
| `apt-dependencies.list`     | Step 1 packages: jq, lm-sensors, chrony, smartmontools, postfix, python3, …                 |

### `setup-pve-node.sh` — step index

1 APT · 2 Hibernate · 3 WoL · 4 Locales · 5 lm-sensors · 6 chrony · 7 `/etc/hosts` · 8 Tailscale · 9 `tailscale up` · 10 post-startup · 11 pre-shutdown · 12 email · 13 SMART · 14 firewall enable · 15 subscription nag · 16 vzdump cron · 17 Tailscale TLS

### Node-installed artifacts (when steps enabled)

| Path                                                        | Step     | Role                                 |
| ----------------------------------------------------------- | -------- | ------------------------------------ |
| `/usr/local/sbin/papita-smart-scan.sh`                      | 13       | SMART health cron target             |
| `/usr/local/sbin/papita-vzdump-all.sh`                      | 16       | Backup all VMs/CTs on node           |
| `/usr/local/sbin/papita-pve-tailscale-cert-renew.sh`        | 17       | Renew UI cert from Tailscale         |
| `/etc/cron.d/papita-{smart-scan,vzdump-all,tailscale-cert}` | 13/16/17 | Scheduled jobs                       |
| `/etc/default/papita-post-startup`                          | 10       | `QUORUM_WAIT_SEC`                    |
| `/etc/default/papita-pre-shutdown`                          | 11       | `ENABLE_STOPALL`, `STOPALL_TIMEOUT`  |
| `/etc/default/pve-main-node`                                | 10.2     | Main node hostname for WoL           |
| `/etc/hosts` (marked block)                                 | 7        | `# BEGIN papita-pve-cluster-hosts` … |

### `src/bash/misc/tailscale/`

| File                      | Role                                                           |
| ------------------------- | -------------------------------------------------------------- |
| `default.tags.list`       | Tailscale ACL tags (e.g. `tag:private-node`)                   |
| `default.gateways.list`   | Optional PVE `--advertise-routes` (empty; pfSense handles LAN) |
| `default.lan.routes.list` | Main-node fallback LAN route (`172.16.0.0/16`)                 |

### `src/python/misc/cluster/`

| File                | Role                                                               |
| ------------------- | ------------------------------------------------------------------ |
| `discover_hosts.py` | Step 7 CLI: DNS peer discovery → `/etc/hosts` lines                |
| `domain_pattern.py` | Wildcard domain suffix keywords (`oldtimers.*`, `*.oldtimers.lan`) |

### `src/python/data/`

| File                           | Role                                                     |
| ------------------------------ | -------------------------------------------------------- |
| `default.hosts.list`           | Candidate short hostnames for DNS discovery              |
| `default.hosts.regex`          | Default FQDN regex (e.g. `^pve(node)?-[0-9]{3}(\..+)?$`) |
| `default.domain.suffixes.list` | Zone labels expanded for trailing `.*` domain keywords   |

Deployed to `/root/deploy/python/` on PVE nodes (`misc/cluster/` + `data/`).

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

| Concern                    | Primary file(s)                                                |
| -------------------------- | -------------------------------------------------------------- |
| Python lint/format         | `pyproject.toml`, `.pre-commit-config.yaml`                    |
| Git exclusions             | `.gitignore`                                                   |
| AWS/Terraform env          | `terraform/environments/config.<env>.tfvars` (local)           |
| EFS mount path             | `terraform/plans/main.tf` locals → default `/pve`              |
| Tailscale CIDR for EFS SG  | `plan_specific_aws_security_params` → default `100.64.0.0/10`  |
| PVE Tailscale tags/routes  | `src/bash/misc/tailscale/default.*.list`                       |
| PVE cluster host discovery | `src/python/misc/cluster/` + `src/python/data/default.hosts.*` |
| PVE setup manual           | `deploy/data/setup-pve-node.usage.txt`                         |
| PVE step count / skip      | `PVE_SETUP_LAST_STEP`, `_skip_pve_step` in `setup-pve-node.sh` |
| SSH to PVE                 | `PAPITA_SSH_PASSWORD` env or SSH keys                          |
| AWS auth in toolkit        | `--aws-sso`, `--aws-mfa`, `--env-file`, `AWS_PROFILE`          |

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
