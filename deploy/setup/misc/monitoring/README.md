# Papita lab monitoring (no secrets)

Versioned scripts, Prometheus scrape/rule config, Grafana dashboard JSON, Kubernetes collectors, and guest-firewall examples. Tokens, Grafana passwords, and Uptime Kuma credentials stay on the hosts.

## Layout

| Path                                    | Role                                                                                     |
| --------------------------------------- | ---------------------------------------------------------------------------------------- |
| `k8s-monitor/`                          | Docker Compose stack for LXC **231** (`172.16.20.11`): Prometheus, Alertmanager, Grafana |
| `k8s-monitor/prometheus/prometheus.yml` | Scrape jobs: k8s API SD, kube-state-metrics proxy, PVE `:9100`                           |
| `k8s-monitor/prometheus/rules/`         | Recording + alerting heuristics (`k8s.yml`, `pve.yml`)                                   |
| `k8s-monitor/grafana/provisioning/`     | Datasource + Papita folder dashboards (`papita-k8s`, `papita-pve`)                       |
| `k8s-monitor/alertmanager/`             | Stub receiver (blackhole until Slack/email is wired)                                     |
| `kubernetes/`                           | In-cluster kube-state-metrics, node-exporter (hostNetwork), Prometheus SA/RBAC           |
| `firewall/`                             | Guest fw templates for CT 231 and Uptime Kuma CT 1004                                    |
| `papita-sync-k8s-monitor.sh`            | Push stack into CT 231; preserve `grafana.env` and bearer token                          |
| `papita-pve-node-exporter.sh`           | Install `prometheus-node-exporter` on a PVE node                                         |
| `papita-k8s-monitor-ct-firewall.sh`     | Write `/etc/pve/firewall/231.fw`                                                         |
| `papita-k8s-api-hosts.sh`               | Pin `api.k8s.oldtimers.lab` → `172.16.30.10` on k8s VMs                                  |
| `papita-apply-k8s-metrics.sh`           | `kubectl apply` collectors (does not mint tokens)                                        |
| `papita_uptime_kuma_bootstrap.py`       | Uptime Kuma monitors (LXC 1004)                                                          |
| `papita-uptime-kuma-firewall.sh`        | Guest fw for Kuma `:3001`                                                                |
| `default.*.env.example`                 | Non-secret layout knobs                                                                  |

## Endpoints (lab)

- Grafana: `http://172.16.20.11:3000` (admin password only on the CT `grafana.env`)
- Prometheus: `http://172.16.20.11:9090`
- Alertmanager: `http://172.16.20.11:9093`
- PVE node-exporter: `172.16.0.101–104:9100`
- k8s API VIP: `https://172.16.30.10:6443`

## Apply (workstation)

```bash
./deploy/proxmox.sh setup-monitoring --ip-address 172.16.0.101
```

That copies this folder to `/root/deploy/misc/monitoring`, installs node-exporter on all PVE nodes, writes `231.fw`, and syncs compose/rules/dashboards into LXC 231 (keeps `grafana.env` and the bearer token on the CT).

Per-node during `setup-pve-node.sh` step 19: `papita-pve-node-exporter.sh`.

Kubernetes collectors (needs `kubectl`):

```bash
/root/deploy/misc/monitoring/papita-apply-k8s-metrics.sh
```
