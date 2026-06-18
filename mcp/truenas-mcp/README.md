# TrueNAS MCP Server

[Model Context Protocol](https://modelcontextprotocol.io/) server for **TrueNAS SCALE** (25.04+) using the **WebSocket JSON-RPC API** (`wss://host/websocket`).

Designed for the papita-proxmox-lab homelab: NFS storage for Proxmox HA on `pvecm-oldtimers`, **Scrutiny** on the NAS, and **Uptime Kuma** on the PVE cluster.

## Quick start

From the **repo root**:

```bash
./deploy/mcp.sh install --server truenas-mcp
./deploy/mcp.sh cursor-sync
```

Edit `~/.cursor/mcp.json` → set `TRUENAS_API_KEY` (TrueNAS UI → user icon → **My API Keys**).

Reload Cursor. In Settings → MCP, confirm `truenas` is green.

```bash
./deploy/mcp.sh smoke --server truenas-mcp
./deploy/mcp.sh smoke --server truenas-mcp --extended
```

**Basic smoke (~18 checks):** config, auth, system, pools, alerts, NFS, SMART, alert policies, apps (Scrutiny), datasets, disks, jobs, scrubs.

**Extended (`--extended`, +9 checks):** disk temperature, reporting graph, MCP tool wrappers.

See [docs/SMOKE_TESTS.md](./docs/SMOKE_TESTS.md) for the full matrix.

## Configuration

| Variable                        | Default                                         | Description                                            |
| ------------------------------- | ----------------------------------------------- | ------------------------------------------------------ |
| `TRUENAS_HOST`                  | _(required)_                                    | Hostname or IP (e.g. `172.16.0.100` or Tailscale DNS)  |
| `TRUENAS_PORT`                  | `443`                                           | HTTPS/WSS port                                         |
| `TRUENAS_API_KEY`               | _(required)_                                    | API key from TrueNAS UI                                |
| `TRUENAS_VERIFY_SSL`            | `false`                                         | Set `true` when using a trusted CA cert                |
| `TRUENAS_WS_PATH`               | `/websocket`                                    | WebSocket path (`/api/v2.0/websocket` on older builds) |
| `TRUENAS_WS_PING_INTERVAL_SEC`  | `30`                                            | WebSocket keepalive ping interval (`0` disables)       |
| `TRUENAS_LAB_HA_POOL_NAME`      | `pve-cluster-oldtimers-ha-storage`              | Expected HA ZFS pool                                   |
| `TRUENAS_LAB_NFS_EXPORT`        | `/mnt/pve-cluster-oldtimers-ha-storage/pve-nfs` | NFS export path                                        |
| `TRUENAS_LAB_SCRUTINY_APP_NAME` | `scrutiny`                                      | Scrutiny app name in `app.query`                       |
| `TRUENAS_LAB_CONFIG_FILE`       | _(optional)_                                    | Path to `default.truenas.nfs.env` overlay              |
| `TRUENAS_LOG_LEVEL`             | `INFO`                                          | stderr JSON log level                                  |

**Security:** Always use `wss://`. TrueNAS revokes API keys sent over plain HTTP.

## Read tools (v1 + v1.1)

| Tool                          | TrueNAS method(s)                       | Purpose                             |
| ----------------------------- | --------------------------------------- | ----------------------------------- |
| `truenas_get_system_info`     | `system.info`, `system.state`           | Version, uptime, middleware state   |
| `truenas_check_api_key`       | `system.state`, `system.info`           | Auth validation + session metadata  |
| `truenas_list_alerts`         | `alert.list`                            | Active alerts                       |
| `truenas_list_alert_policies` | `alert.list_policies`                   | Alert notification policies         |
| `truenas_list_pools`          | `pool.query`                            | ZFS pool health                     |
| `truenas_list_datasets`       | `pool.dataset.query`                    | Dataset space / mount points        |
| `truenas_list_disks`          | `disk.query`, `disk.temperature_alerts` | Disk inventory + thermal alerts     |
| `truenas_list_smart_results`  | `smart.test.results`                    | SMART tests (complements Scrutiny)  |
| `truenas_get_reporting_data`  | `reporting.get_data`                    | CPU/memory/disk graphs              |
| `truenas_list_apps`           | `app.query`                             | Scrutiny + Tailscale inventory      |
| `truenas_list_jobs`           | `core.get_jobs`                         | Scrubs, replication, updates        |
| `truenas_list_nfs_shares`     | `sharing.nfs.query`                     | NFS exports; lab HA path validation |
| `truenas_list_scrub_tasks`    | `pool.scrub.query`                      | Scrub schedules                     |
| `truenas_system_summary`      | _(aggregate)_                           | Operator dashboard                  |
| `truenas_run_smoke_tests`     | _(smoke)_                               | Post-install verification           |

## Write tools (v2, gated)

All write tools require **`confirm=true`**.

| Tool                       | TrueNAS method        | Purpose                  |
| -------------------------- | --------------------- | ------------------------ |
| `truenas_create_dataset`   | `pool.dataset.create` | Create ZFS dataset       |
| `truenas_update_nfs_share` | `sharing.nfs.update`  | Enable/disable NFS share |
| `truenas_dismiss_alert`    | `alert.dismiss`       | Dismiss active alert     |

## Lab monitoring split

| Service         | Host                      | MCP / automation                                                                 |
| --------------- | ------------------------- | -------------------------------------------------------------------------------- |
| **Scrutiny**    | TrueNAS app (`scrutiny`)  | `truenas_list_apps`, `truenas_list_smart_results`; WebUI via runbook             |
| **Uptime Kuma** | Proxmox `pvecm-oldtimers` | `proxmox-ve` MCP; `deploy/setup/misc/monitoring/papita_uptime_kuma_bootstrap.py` |

Requirements traceability: [docs/REQUIREMENTS.md](./docs/REQUIREMENTS.md). API key setup: [docs/API_KEY_SETUP.md](./docs/API_KEY_SETUP.md).

## API key setup

1. Log into TrueNAS WebUI.
2. User icon (top-right) → **My API Keys** → **Add**.
3. Name it (e.g. `mcp-cursor-agent`); prefer a dedicated service user with least privilege.
4. Copy the key immediately (shown once).
5. Paste into `~/.cursor/mcp.json` under `mcpServers.truenas.env.TRUENAS_API_KEY`.

## Related lab docs

- [TIPSNTRICKS — TrueNAS NFS + HA](../../docs/TIPSNTRICKS.md)
- [default.truenas.nfs.env](../../deploy/setup/misc/cluster/default.truenas.nfs.env)

## Official alternatives

TrueNAS Labs publishes [truenas/truenas-mcp](https://github.com/truenas/truenas-mcp) (research preview). This package is a papita-native, repo-integrated server aligned with `proxmox-ve-mcp` and `pfsense-mcp` conventions. Do not register both under the same Cursor server id `truenas`.
