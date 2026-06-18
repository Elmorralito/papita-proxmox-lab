# TrueNAS MCP — Smoke tests

Post-install verification for `truenas-mcp`. Mirrors the pattern used by `proxmox-ve-mcp`.

## Run

From repo root (loads `TRUENAS_*` from `~/.cursor/mcp.json` when present):

```bash
./deploy/mcp.sh smoke --server truenas-mcp
./deploy/mcp.sh smoke --server truenas-mcp --extended
```

Or directly:

```bash
poetry run truenas-mcp-smoke
poetry run truenas-mcp-smoke --extended
```

MCP tool: `truenas_run_smoke_tests(extended=false|true)`.

## Core checks (must pass)

| Check            | Meaning                        |
| ---------------- | ------------------------------ |
| `config_valid`   | `TRUENAS_HOST` + API key set   |
| `websocket_auth` | `system.state` over WSS        |
| `system_info`    | `system.info` returns hostname |
| `pools_query`    | At least one ZFS pool          |

Exit code **0** when `core_passed` is true (warnings on lab-specific checks are OK).

## Standard checks (basic run)

| Check                  | Optional | Notes                              |
| ---------------------- | -------- | ---------------------------------- |
| `system_state_ready`   | no       | Expect `READY`                     |
| `pools_all_online`     | no       | Fail if any pool not `ONLINE`      |
| `lab_ha_pool`          | **yes**  | `pve-cluster-oldtimers-ha-storage` |
| `alerts_listable`      | no       | `alert.list`                       |
| `alerts_no_critical`   | **yes**  | Warn on WARNING/CRITICAL           |
| `nfs_shares_listable`  | no       | `sharing.nfs.query`                |
| `lab_nfs_export`       | **yes**  | Export path contains lab NFS mount |
| `smart_results_query`  | no       | `smart.test.results` (v1.1)        |
| `alert_policies_query` | no       | `alert.list_policies` (v1.1)       |
| `apps_query`           | no       | `app.query`                        |
| `scrutiny_app_running` | **yes**  | Scrutiny app `RUNNING` on NAS      |
| `datasets_query`       | no       | `pool.dataset.query`               |
| `disks_query`          | no       | `disk.query`                       |
| `jobs_query`           | no       | `core.get_jobs`                    |
| `scrub_tasks_query`    | no       | `pool.scrub.query`                 |

## Extended checks (`--extended`)

| Check                     | Optional | Notes                                   |
| ------------------------- | -------- | --------------------------------------- |
| `disk_temperature_alerts` | **yes**  | May need extra API perms on some builds |
| `reporting_graph`         | **yes**  | `reporting.get_data` cpu graph          |
| `*_tool`                  | no       | MCP tool wrapper smoke (5 tools)        |

## Lab-specific configuration

Override defaults via environment:

| Variable                        | Default                                         |
| ------------------------------- | ----------------------------------------------- |
| `TRUENAS_LAB_HA_POOL_NAME`      | `pve-cluster-oldtimers-ha-storage`              |
| `TRUENAS_LAB_NFS_EXPORT`        | `/mnt/pve-cluster-oldtimers-ha-storage/pve-nfs` |
| `TRUENAS_LAB_SCRUTINY_APP_NAME` | `scrutiny`                                      |
| `TRUENAS_LAB_CONFIG_FILE`       | Optional path to `default.truenas.nfs.env`      |

**Uptime Kuma** runs on Proxmox cluster `pvecm-oldtimers`, not TrueNAS. Use `proxmox-ve` MCP and `deploy/setup/misc/monitoring/papita_uptime_kuma_bootstrap.py`.

## Integration pytest

```bash
TRUENAS_INTEGRATION=1 poetry run pytest mcp/truenas-mcp/tests/test_integration.py -v
```

Requires live `TRUENAS_*` credentials in the environment.
