# Papita lab monitoring (no secrets)

Versioned scripts, Prometheus scrape/rule config, Grafana dashboard JSON, Kubernetes collectors, and guest-firewall examples. Tokens, Grafana passwords, and Uptime Kuma credentials stay on the hosts.

## Layout

| Path                                    | Role                                                                                  |
| --------------------------------------- | ------------------------------------------------------------------------------------- |
| `k8s-monitor/`                          | Docker Compose stack for LXC **231** (`172.16.20.11`): Prometheus, Alertmanager       |
| `k8s-monitor/prometheus/prometheus.yml` | Scrape jobs: k8s API SD, kube-state-metrics proxy, PVE `:9100`                        |
| `k8s-monitor/prometheus/rules/`         | Recording + alerting heuristics (`k8s.yml`, `pve.yml`)                                |
| `qdevice-grafana/provisioning/`         | Grafana on the QDevice Pi: datasources + dashboards (`papita-k8s/pve/scrutiny`)       |
| `papita-qdevice-grafana.sh`             | Run **on the QDevice Pi**: install Grafana, Infinity plugin, provisioning, guardrails |
| `k8s-monitor/alertmanager/`             | Stub receiver (blackhole until Slack/email is wired)                                  |
| `kubernetes/`                           | In-cluster kube-state-metrics, node-exporter (hostNetwork), Prometheus SA/RBAC        |
| `firewall/`                             | Guest fw templates for CT 231 and Uptime Kuma CT 1004                                 |
| `papita-sync-k8s-monitor.sh`            | Push stack into CT 231; preserve bearer token; removes the retired Grafana container  |
| `papita-pve-node-exporter.sh`           | Install `prometheus-node-exporter` on a PVE node                                      |
| `papita-k8s-monitor-ct-firewall.sh`     | Write `/etc/pve/firewall/231.fw`                                                      |
| `papita-k8s-api-hosts.sh`               | Pin `api.k8s.oldtimers.lab` → `172.16.30.10` on k8s VMs                               |
| `papita-apply-k8s-metrics.sh`           | `kubectl apply` collectors (does not mint tokens)                                     |
| `papita_uptime_kuma_bootstrap.py`       | Uptime Kuma monitors (LXC 1004)                                                       |
| `papita-uptime-kuma-firewall.sh`        | Guest fw for Kuma `:3001`                                                             |
| `default.*.env.example`                 | Non-secret layout knobs                                                               |

## Endpoints (lab)

- Grafana: `http://172.16.0.99:3000` on `raspi-qdevice-oldtimers` (admin password only in `/etc/grafana/papita.env` on the Pi)
- Prometheus: `http://172.16.20.11:9090`
- Alertmanager: `http://172.16.20.11:9093`
- PVE node-exporter: `172.16.0.101–104:9100`; QDevice Pi node-exporter: `172.16.0.99:9100` (job `qdevice`)
- Scrutiny (TrueNAS app): `http://172.16.0.100:31054` (read by Grafana's Infinity datasource via `/api/summary`)
- k8s API VIP: `https://172.16.30.10:6443`

## Apply (workstation)

```bash
./deploy/proxmox.sh setup-monitoring --ip-address 172.16.0.101
```

That copies this folder to `/root/deploy/misc/monitoring`, installs node-exporter on all PVE nodes, writes `231.fw`, and syncs compose/rules into LXC 231 (keeps the bearer token on the CT). The first sync after the Grafana move runs `docker compose up -d --remove-orphans`, which removes the old `grafana` container; the `grafana_data` volume stays on the CT until you delete it.

Per-node during `setup-pve-node.sh` step 19: `papita-pve-node-exporter.sh`.

Kubernetes collectors (needs `kubectl`):

```bash
/root/deploy/misc/monitoring/papita-apply-k8s-metrics.sh
```

## Grafana on the QDevice Pi

Grafana runs on `raspi-qdevice-oldtimers` (outside the PVE cluster) and reads Prometheus on CT 231 plus Scrutiny on TrueNAS. Install Grafana on the Pi **before** the next `setup-monitoring`, which removes Grafana from CT 231.

```bash
scp -r deploy/setup/misc/monitoring root@172.16.0.99:/root/papita-monitoring
ssh root@172.16.0.99 'bash /root/papita-monitoring/papita-qdevice-grafana.sh'
# First run writes /etc/grafana/papita.env and stops: set GF_SECURITY_ADMIN_PASSWORD there, then re-run.
```

Guardrails (corosync-qnetd keeps priority): Grafana gets `Nice=10`, `CPUWeight=50`, `CPUQuota=150%`, `IOSchedulingClass=idle`, `OOMScoreAdjust=500`, `MemoryHigh=600M`/`MemoryMax=800M`, and logs only to journald. `corosync-qnetd` gets `Nice=-5`, `CPUWeight=1000`, `OOMScoreAdjust=-900`. The script applies these to the running qnetd process without restarting it.

> [!WARNING]
> Stock Raspberry Pi OS disables the memory cgroup, so `MemoryHigh`/`MemoryMax` are accepted but **not enforced** (the script warns). To enforce them, add `cgroup_enable=memory cgroup_memory=1` to `/boot/firmware/cmdline.txt` (single line) and reboot. Check `pvecm status` first, because the reboot temporarily removes the QDevice vote.

Knobs (env): `PAPITA_GRAFANA_VERSION` (pin + `apt-mark hold`), `PAPITA_PROMETHEUS_URL`, `PAPITA_SCRUTINY_URL`, `PAPITA_GRAFANA_PORT`, `PAPITA_GRAFANA_ROOT_URL`.

The Scrutiny dashboard (`papita-scrutiny`) needs the Infinity plugin (Grafana ≥ 11.6). It shows the current status, temperature, and power-on hours for each disk. Temperature history stays in Scrutiny's own WebUI.
