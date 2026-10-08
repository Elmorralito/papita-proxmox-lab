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
| `.gitignore`              | `.env`, `poetry.lock`, drawio backups                                                     |

---

## `.cursor/` — Cursor agent config

| File                                                 | Role                                                  |
| ---------------------------------------------------- | ----------------------------------------------------- |
| `.cursor/rules/repo-map.mdc`                         | Always-on repo identity, tree, workflows, conventions |
| `.cursor/skills/papita-proxmox-lab-map/SKILL.md`     | On-demand deep map skill (this skill)                 |
| `.cursor/skills/papita-proxmox-lab-map/reference.md` | Full file inventory (this file)                       |

---

## `deploy/` — Orchestration (run from repo root)

| File                       | Role                                                                                                            |
| -------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `toolkit.sh`               | Main CLI: `build`, `devsync`, `test`, `proxmox`, AWS auth, pre-commit                                           |
| `proxmox.sh`               | SSH to PVE: `setup-node`, `setup-cluster-ha`, `setup-monitoring`, `get-temp`, cluster start/stop                |
| `mcp.sh`                   | Install / test / smoke / cursor-sync MCP servers                                                                |
| `utils.sh`                 | Shared helpers: `log`, `prompt_pve_start`, `prompt_until_*`, `prompt_crontab_schedule`, AWS auth, `run_command` |
| `usage.sh`                 | Help text: `usage_toolkit`, `usage_proxmox`, `usage_setup_pve_node`                                             |
| `tailscale-pfsense-lan.sh` | Workstation helper: Tailscale ACL + pfSense LAN integration                                                     |

### `deploy/docs/`

| File                              | Role                                                 |
| --------------------------------- | ---------------------------------------------------- |
| `setup-pve-node.usage.txt`        | Full manual for 17-step PVE setup (shown via `less`) |
| `tailscale-pfsense-lan.usage.txt` | Usage for `tailscale-pfsense-lan.sh`                 |

### `toolkit.sh` functions

`build`, `devsync`, `run_pytest`, `deploy_proxmox`, `pre_commit`, `aws_cli`

### `proxmox.sh` functions

`setup_node`, `get_cluster_nodes`, `get_local_node`, `start_cluster`, `stop_cluster`, `get_cluster_temperature`, SSH helpers (`_pve_ssh_capture`, `_pve_cluster_for_each_remote_ssh`, `_pve_print_sensors_table`)

---

## `deploy/setup/` — PVE node scripts (SCP'd to `/root/deploy`)

| File                        | Role                                                                                        |
| --------------------------- | ------------------------------------------------------------------------------------------- |
| `setup-pve-node.sh`         | Interactive 19-step PVE bootstrap; `PVE_SETUP_LAST_STEP=19`, `_skip_pve_step`               |
| `post-startup-proc.sh`      | Boot: quorum wait (`/etc/default/papita-post-startup`), ceph noout unset, WoL               |
| `pre-shutdown-proc.sh`      | Shutdown: optional `pvesh stopall`, ceph osd set noout (`/etc/default/papita-pre-shutdown`) |
| `post-startup-proc.service` | systemd unit for post-startup hook                                                          |
| `pre-shutdown-proc.service` | systemd unit for pre-shutdown hook                                                          |
| `apt-dependencies.list`     | Step 1 packages: jq, lm-sensors, chrony, smartmontools, postfix, python3, …                 |

### `setup-pve-node.sh` — step index

1 APT · 2 Hibernate · 3 WoL · 4 Locales · 5 lm-sensors · 6 chrony · 7 `/etc/hosts` · 8 Tailscale · 9 `tailscale up` · 10 post-startup · 11 pre-shutdown · 12 email · 13 SMART · 14 firewall enable · 15 subscription nag · 16 vzdump cron · 17 Tailscale TLS · 18 QDevice · 19 node-exporter

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

### `deploy/setup/misc/tailscale/`

| File                      | Role                                                           |
| ------------------------- | -------------------------------------------------------------- |
| `default.tags.list`       | Tailscale ACL tags (e.g. `tag:private-node`)                   |
| `default.gateways.list`   | Optional PVE `--advertise-routes` (empty; pfSense handles LAN) |
| `default.lan.routes.list` | Main-node fallback LAN route (`172.16.0.0/16`)                 |

### `deploy/setup/misc/cluster/`

| File                            | Role                                                          |
| ------------------------------- | ------------------------------------------------------------- |
| `default.qdevice.host`          | Dedicated QDevice IP (`corosync-qnetd`; not PVE, not TrueNAS) |
| `default.truenas.nfs.env`       | TrueNAS NFS + HA group defaults (`172.16.0.100`)              |
| `qdevice-server-bootstrap.sh`   | Run on QDevice host: install `corosync-qnetd`                 |
| `papita-node-qdevice-client.sh` | Per PVE node: `corosync-qdevice` + `softdog` (step 18)        |
| `papita-cluster-quorum-ha.sh`   | Cluster: NFS storage, `pvecm qdevice setup`, HA group         |

### `deploy/setup/misc/monitoring/`

Versioned lab monitoring (no tokens). Live Grafana/Prometheus: LXC **231** `172.16.20.11`. Uptime Kuma: LXC **1004**.

| File                                        | Role                                                        |
| ------------------------------------------- | ----------------------------------------------------------- |
| `README.md`                                 | Inventory and apply commands                                |
| `default.k8s-monitor.env.example`           | CT 231 / API VIP / node-exporter IPs                        |
| `default.uptime-kuma.env.example`           | Kuma URL/layout knobs (password empty)                      |
| `papita-sync-k8s-monitor.sh`                | Push compose/rules/dashboards into CT 231                   |
| `papita-pve-node-exporter.sh`               | Install `prometheus-node-exporter` on PVE                   |
| `papita-k8s-monitor-ct-firewall.sh`         | Guest fw for Grafana/Prometheus/AM                          |
| `papita-k8s-api-hosts.sh`                   | `api.k8s.oldtimers.lab` → `172.16.30.10`                    |
| `papita-apply-k8s-metrics.sh`               | `kubectl apply` collectors                                  |
| `papita-uptime-kuma-firewall.sh`            | Guest fw for Kuma `:3001`                                   |
| `papita_uptime_kuma_bootstrap.py`           | Kuma monitors + optional Telegram template                  |
| `firewall/231.fw` / `1004.fw`               | Guest firewall templates                                    |
| `k8s-monitor/docker-compose.yml`            | Prometheus + Alertmanager + Grafana                         |
| `k8s-monitor/prometheus/prometheus.yml`     | Scrape jobs (k8s SD + PVE `:9100`)                          |
| `k8s-monitor/prometheus/rules/*.yml`        | Recording rules and alerts                                  |
| `k8s-monitor/grafana/provisioning/`         | Datasource + Papita dashboards JSON                         |
| `k8s-monitor/alertmanager/alertmanager.yml` | Stub blackhole receiver                                     |
| `kubernetes/*.yaml`                         | Namespace, Prometheus SA, kube-state-metrics, node-exporter |

### `deploy/python/misc/cluster/`

| File                | Role                                                               |
| ------------------- | ------------------------------------------------------------------ |
| `discover_hosts.py` | Step 7 CLI: DNS peer discovery → `/etc/hosts` lines                |
| `domain_pattern.py` | Wildcard domain suffix keywords (`oldtimers.*`, `*.oldtimers.lan`) |

### `deploy/python/datafiles/`

| File                           | Role                                                     |
| ------------------------------ | -------------------------------------------------------- |
| `default.hosts.list`           | Candidate short hostnames for DNS discovery              |
| `default.hosts.regex`          | Default FQDN regex (e.g. `^pve(node)?-[0-9]{3}(\..+)?$`) |
| `default.domain.suffixes.list` | Zone labels expanded for trailing `.*` domain keywords   |

Deployed to `/root/deploy/python/` on PVE nodes (`misc/cluster/` + `datafiles/`).

---

## `docs/` — Documentation

| File              | Role                                    |
| ----------------- | --------------------------------------- |
| `TIPSNTRICKS.md`  | Ceph, OSD, cluster maintenance runbooks |
| `Diagrams.drawio` | Network/architecture diagram (editable) |

Referenced in README but may be exported separately: `docs/Diagrams-Network.png`

---

## `rules-tmp/` — Draft Cursor rules (not active)

| File              | Role                          |
| ----------------- | ----------------------------- |
| `bash_deploy.mdc` | Draft bash deploy conventions |

Active rules live in `.cursor/rules/`.

---

## Referenced but absent from repo

| Path     | Expected role                               |
| -------- | ------------------------------------------- |
| `libs/`  | Python packages built by `toolkit.sh build` |
| `tests/` | pytest suite run by `toolkit.sh test`       |
| `dist/`  | Built wheels output (generated)             |
| `.venv/` | Poetry virtualenv (generated, in-project)   |

---

## Configuration cross-reference

| Concern                    | Primary file(s)                                                           |
| -------------------------- | ------------------------------------------------------------------------- |
| Python lint/format         | `pyproject.toml`, `.pre-commit-config.yaml`                               |
| Git exclusions             | `.gitignore`                                                              |
| Proxmox API (MCP)          | `PVE_*` env vars in `~/.cursor/mcp.json`                                  |
| PVE Tailscale tags/routes  | `deploy/setup/misc/tailscale/default.*.list`                              |
| PVE cluster host discovery | `deploy/python/misc/cluster/` + `deploy/python/datafiles/default.hosts.*` |
| Lab metrics / Grafana      | `deploy/setup/misc/monitoring/` (secrets stay on CT 231 / Kuma)           |
| PVE setup manual           | `deploy/docs/setup-pve-node.usage.txt`                                    |
| PVE step count / skip      | `PVE_SETUP_LAST_STEP`, `_skip_pve_step` in `setup-pve-node.sh`            |
| SSH to PVE                 | `PAPITA_SSH_PASSWORD` env or SSH keys                                     |
| AWS auth in toolkit        | `--aws-sso`, `--aws-mfa`, `--env-file`, `AWS_PROFILE`                     |

---

## Pre-commit hooks (active)

| Hook                                                                               | Source                                |
| ---------------------------------------------------------------------------------- | ------------------------------------- |
| trailing-whitespace, end-of-file-fixer, check-yaml, check-toml, detect-private-key | pre-commit-hooks v5.0.0               |
| prettier (_.yaml, _.yml)                                                           | mirrors-prettier                      |
| shellcheck                                                                         | shellcheck-precommit v0.10.0          |
| isort                                                                              | pycqa/isort 6.0.1                     |
| black                                                                              | psf/black 25.1.0                      |
| flake8                                                                             | pycqa/flake8 7.1.2                    |
| pylint                                                                             | local (system, pyproject.toml rcfile) |
| mypy                                                                               | mirrors-mypy v1.15.0                  |

Commented out: check-unused-vars, yamllint duplicates, interrogate duplicates.
