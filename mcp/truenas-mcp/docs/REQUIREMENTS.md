# TrueNAS MCP Server — Requirements & Traceability

**Project:** `papita-proxmox-lab` / `mcp/truenas-mcp`
**Package version:** 0.2.0a1
**Requirements version:** 0.2
**Date:** 2026-06-16
**Status:** v1.1 read + v2 gated writes — roadmap implemented

**Automated compliance checks:** `tests/test_requirements_compliance.py`

**Traceability legend:** **Met** | **Partial** | **N/A** (won't/deferred) | **Doc** (documented only)

Onboarding: [README.md](../README.md). API key setup: [API_KEY_SETUP.md](./API_KEY_SETUP.md).

---

## 1. Executive summary

- **Goal:** Typed MCP server so agents **inspect** TrueNAS storage health in this lab without WebGUI or ad-hoc scripts — especially for **Proxmox HA NFS** on `172.16.0.100`.
- **API:** Official TrueNAS middleware over **WebSocket JSON-RPC** (`wss://host/websocket`); REST deprecated in 25.04+, removed in 26.x.
- **v1 delivered:** **Read-only** — 10 MCP tools (v0.1).
- **v1.1 delivered:** +5 read tools (API key check, SMART, alert policies, reporting, apps/Scrutiny).
- **v2 delivered:** 3 gated write tools (`confirm=true`); no destructive operations.
- **Auth:** API key via `auth.login_with_api_key` on persistent WebSocket; **wss:// only** (keys revoked over HTTP).
- **Positioning vs official:** [truenas/truenas-mcp](https://github.com/truenas/truenas-mcp) (Go, research preview, broad coverage) remains the upstream reference. This package is **papita-native**: Poetry, `deploy/mcp.sh`, runbook traceability, lab NFS/HA focus — not a fork of the official binary.

---

## 2. Discovery findings

### 2.1 Existing automation inventory

| Source                    | Operation                    | Mechanism                           | Read / Write        | API mapping                                 | MCP v1                                                        |
| ------------------------- | ---------------------------- | ----------------------------------- | ------------------- | ------------------------------------------- | ------------------------------------------------------------- |
| `deploy/proxmox.sh`       | `setup-cluster-ha`           | SSH → `papita-cluster-quorum-ha.sh` | Write               | `pvesm add nfs`, ping NFS                   | **Partial** — NFS export verify via `truenas_list_nfs_shares` |
| `default.truenas.nfs.env` | NFS server/export defaults   | Env file                            | Config              | `172.16.0.100`, export path                 | **Partial** — warnings in `truenas_system_summary`            |
| `docs/TIPSNTRICKS.md`     | Pool health, SMART, Scrutiny | Manual WebGUI + apps                | Read                | `pool.query`, `disk.*`, `smart.*`           | **Partial** — pools/disks; no Scrutiny API                    |
| `docs/TIPSNTRICKS.md`     | HA verify                    | `pvesm status`, `ha-manager status` | Read                | PVE-side only                               | **N/A** — use proxmox-ve MCP                                  |
| `docs/TIPSNTRICKS.md`     | Uptime Kuma / monitoring     | TrueNAS apps                        | Read                | No unified app health API                   | **N/A** — out of v1                                           |
| Bash / WebGUI             | Dataset create, share ACL    | UI / CLI                            | Write / Destructive | `pool.dataset.create`, `sharing.nfs.update` | **N/A** — v2+ gated writes                                    |

### 2.2 Access patterns

```text
Workstation (Cursor / deploy scripts)
    │
    ├── LAN 172.16.0.0/16 ──► TrueNAS 172.16.0.100:443 (wss://)
    │                             └── MCP entry point (API key)
    │
    └── Tailscale 100.x ──► optional (hostname allowed in TRUENAS_HOST)
                              └── proxmox-ve MCP for PVE HA side
```

**Implication:** MCP connects to **TrueNAS middleware WebSocket**. Proxmox NFS mount state stays in **proxmox-ve MCP** + Bash (`pvesm status`).

### 2.3 Personas

| Persona               | Goals                                                  | Primary sources                                 |
| --------------------- | ------------------------------------------------------ | ----------------------------------------------- |
| **Operator**          | Pool ONLINE, alerts, disk temps, scrub status          | TIPSNTRICKS § TrueNAS monitoring                |
| **Deploy engineer**   | Validate NFS export before `setup-cluster-ha`          | `default.truenas.nfs.env`, TIPSNTRICKS § Path B |
| **Troubleshooter**    | Jobs, replication failures, capacity                   | `core.get_jobs`, `pool.dataset.query`           |
| **AI agent (Cursor)** | Read-only checks, runbook refs, cross-hints to PVE MCP | MCP read tools                                  |

### 2.4 Gaps MCP fills vs Bash/WebGUI

| Gap                                   | MCP benefit                                                |
| ------------------------------------- | ---------------------------------------------------------- |
| Manual WebGUI checks before HA setup  | Agent can verify NFS export + pool health in one session   |
| No structured storage JSON for agents | Consistent tool responses with `tool_class`, `runbook_ref` |
| Official MCP not repo-integrated      | Same install path as `proxmox-ve-mcp` / `pfsense-mcp`      |
| Cross-stack incidents                 | `truenas_system_summary` + `proxmox_hint` in meta          |

### 2.5 Build vs buy (official MCP)

| Option                             | Pros                                        | Cons                                       | Decision                          |
| ---------------------------------- | ------------------------------------------- | ------------------------------------------ | --------------------------------- |
| **truenas/truenas-mcp** (official) | Full API, native binary, actively developed | Not in repo; Go binary; research preview   | Reference / optional side-by-side |
| **papita truenas-mcp** (this)      | Poetry, compliance tests, lab runbooks      | Narrower tool set; Python WebSocket client | **Primary for this repo**         |

---

## 3. Business requirements

| ID     | Requirement                                | Priority | Acceptance criteria                                | Status      | Evidence                                                         |
| ------ | ------------------------------------------ | -------- | -------------------------------------------------- | ----------- | ---------------------------------------------------------------- |
| BR-001 | Agents **inspect** TrueNAS without WebGUI  | Must     | Pools, alerts, disks, jobs via JSON tools          | **Met**     | 10 read tools in `register.py`                                   |
| BR-002 | **Classify** tools read/write/destructive  | Must     | Every tool declares class; no destructive v1       | **Met**     | `ToolClass`, `TOOL_REGISTRY`                                     |
| BR-003 | Align with **lab HA/NFS workflows**        | Must     | NFS export + pool health map to TIPSNTRICKS Path B | **Partial** | `truenas_list_nfs_shares`, summary warnings; no PVE-side `pvesm` |
| BR-004 | Reach TrueNAS over LAN/Tailscale           | Must     | `TRUENAS_HOST`; TLS configurable                   | **Met**     | `config.py`; IP or hostname                                      |
| BR-005 | Do **not** replace `setup-cluster-ha` Bash | Won't    | QDevice + `pvesm add nfs` remain Bash              | **N/A**     | Documented §2.1                                                  |
| BR-006 | **Audit trail** for mutating calls         | Should   | Structured logs; no secrets                        | **N/A**     | v1 read-only; scaffold in `log_tool_event`                       |
| BR-007 | **Revocable** API key access               | Must     | Rotation doc; dedicated service user               | **Doc**     | `API_KEY_SETUP.md`                                               |
| BR-008 | Faster incident diagnosis                  | Should   | Summary aggregates alerts/pools/jobs               | **Met**     | `truenas_system_summary`                                         |
| BR-009 | Complement **proxmox-ve MCP**              | Should   | Cross-hints in summary meta                        | **Met**     | `proxmox_hint` in `system.py`                                    |
| BR-010 | **Papita conventions**                     | Must     | `172.16.0.100`, export path constants              | **Met**     | `constants.py`                                                   |
| BR-011 | Acknowledge **official MCP** exists        | Must     | README + this doc                                  | **Met**     | README § Official alternatives                                   |

---

## 4. Functional requirements

### 4.1 System & health

| ID     | Requirement                   | Priority | API method            | Status  | Evidence                      |
| ------ | ----------------------------- | -------- | --------------------- | ------- | ----------------------------- |
| FR-001 | System info (version, uptime) | Must     | `system.info`         | **Met** | `truenas_get_system_info`     |
| FR-002 | Middleware state              | Must     | `system.state`        | **Met** | `truenas_get_system_info`     |
| FR-003 | Active alerts                 | Must     | `alert.list`          | **Met** | `truenas_list_alerts`         |
| FR-004 | Health summary                | Must     | Derived               | **Met** | `truenas_system_summary`      |
| FR-005 | Alert policies                | Should   | `alert.list_policies` | **Met** | `truenas_list_alert_policies` |
| FR-006 | Reporting metrics             | Could    | `reporting.get_data`  | **Met** | `truenas_get_reporting_data`  |

### 4.2 Storage (ZFS)

| ID     | Requirement                 | Priority | API method                | Status  | Evidence                   |
| ------ | --------------------------- | -------- | ------------------------- | ------- | -------------------------- |
| FR-010 | List pools + status         | Must     | `pool.query`              | **Met** | `truenas_list_pools`       |
| FR-011 | List datasets + utilization | Must     | `pool.dataset.query`      | **Met** | `truenas_list_datasets`    |
| FR-012 | Pool scrub tasks/status     | Should   | `pool.scrub.query`        | **Met** | `truenas_list_scrub_tasks` |
| FR-013 | Snapshot tasks              | Could    | `pool.snapshottask.query` | **N/A** | v1.1                       |
| FR-014 | Warn on degraded pools      | Must     | Derived from `pool.query` | **Met** | `pool_health_warnings()`   |

### 4.3 Disks & SMART

| ID     | Requirement             | Priority | API method                | Status  | Evidence                     |
| ------ | ----------------------- | -------- | ------------------------- | ------- | ---------------------------- |
| FR-020 | List disks              | Must     | `disk.query`              | **Met** | `truenas_list_disks`         |
| FR-021 | Disk temperature alerts | Should   | `disk.temperature_alerts` | **Met** | `truenas_list_disks`         |
| FR-022 | SMART test results      | Should   | `smart.test.results`      | **Met** | `truenas_list_smart_results` |
| FR-023 | Aggregated disk temps   | Could    | `disk.temperature_agg`    | **N/A** | v1.1                         |

### 4.4 NFS & Proxmox HA (lab-specific)

| ID     | Requirement           | Priority | API method                  | Status      | Evidence                                        |
| ------ | --------------------- | -------- | --------------------------- | ----------- | ----------------------------------------------- |
| FR-030 | List NFS shares       | Must     | `sharing.nfs.query`         | **Met**     | `truenas_list_nfs_shares`                       |
| FR-031 | Match lab export path | Should   | Derived vs `LAB_NFS_EXPORT` | **Partial** | Warnings in `truenas_list_nfs_shares` + summary |
| FR-032 | SMB shares read       | Could    | `sharing.smb.query`         | **N/A**     | v1.1                                            |

### 4.5 Jobs & maintenance

| ID     | Requirement          | Priority | API method      | Status  | Evidence                 |
| ------ | -------------------- | -------- | --------------- | ------- | ------------------------ |
| FR-040 | List middleware jobs | Must     | `core.get_jobs` | **Met** | `truenas_list_jobs`      |
| FR-041 | Failed job warnings  | Should   | Derived         | **Met** | `truenas_system_summary` |

### 4.6 Diagnostics

| ID     | Requirement              | Priority | Status  | Evidence                                        |
| ------ | ------------------------ | -------- | ------- | ----------------------------------------------- |
| FR-050 | Post-install smoke tests | Must     | **Met** | `truenas_run_smoke_tests`, `truenas-mcp-smoke`  |
| FR-051 | API key / WS auth check  | Should   | **Met** | `truenas_check_api_key`, smoke `websocket_auth` |

### 4.7 Out of scope (v1)

| ID     | Requirement                         | Rationale                        | Status                                                             |
| ------ | ----------------------------------- | -------------------------------- | ------------------------------------------------------------------ |
| FR-900 | App catalog install/upgrade         | Destructive; official MCP covers | **N/A**                                                            |
| FR-901 | VM management                       | Out of lab MCP scope             | **N/A**                                                            |
| FR-902 | `system.reboot` / `system.shutdown` | Destructive                      | **N/A**                                                            |
| FR-903 | Dataset/share mutations             | Data integrity                   | **Met** — v2 gated writes (`confirm=true`)                         |
| FR-904 | Real-time event subscriptions       | Complexity                       | **N/A** — won't                                                    |
| FR-905 | Scrutiny / Uptime Kuma app health   | No stable middleware API         | **Partial** — Scrutiny via `app.query`; Uptime Kuma on PVE cluster |
| FR-906 | QDevice host operations             | Separate host, not TrueNAS       | **N/A**                                                            |

Documented in `BASH_ONLY_WORKFLOWS` (`constants.py`).

---

## 5. Technical requirements

| ID     | Requirement                          | Priority | Status      | Evidence                                      |
| ------ | ------------------------------------ | -------- | ----------- | --------------------------------------------- |
| TR-001 | Python 3.11+ + FastMCP               | Must     | **Met**     | `server.py`, `pyproject.toml`                 |
| TR-002 | stdio transport for Cursor           | Must     | **Met**     | `run_stdio_async()`                           |
| TR-003 | WebSocket client; persistent session | Must     | **Met**     | `client/websocket.py`                         |
| TR-004 | `auth.login_with_api_key`            | Must     | **Met**     | `_connect_and_auth()`                         |
| TR-005 | `TRUENAS_HOST`, port 443             | Must     | **Met**     | `config.py`                                   |
| TR-006 | `TRUENAS_VERIFY_SSL`                 | Should   | **Met**     | Default `false` for homelab                   |
| TR-007 | Configurable `TRUENAS_WS_PATH`       | Must     | **Met**     | `/websocket` default                          |
| TR-008 | Map API errors to tool JSON          | Must     | **Met**     | `TnasApiError`                                |
| TR-009 | Tool naming `truenas_*`              | Must     | **Met**     | `register.py`                                 |
| TR-010 | Pydantic v2 settings                 | Must     | **Met**     | `TnasSettings`                                |
| TR-011 | Query pagination (`limit`)           | Should   | **Partial** | `limit` on datasets/jobs; not all query tools |
| TR-012 | Recv until matching response `id`    | Must     | **Met**     | `_recv_matching()` in websocket client        |
| TR-013 | Secrets from env; never log key      | Must     | **Met**     | `config.py`, `redact_sensitive()`             |
| TR-014 | dotenv                               | Could    | **Met**     | `load_dotenv()`                               |
| TR-015 | Connection reconnect on failure      | Should   | **Partial** | Reset on error; no background keepalive       |
| TR-016 | API key setup doc                    | Must     | **Doc**     | `API_KEY_SETUP.md`                            |
| TR-017 | pytest; integration flag             | Should   | **Partial** | Unit tests; `TRUENAS_INTEGRATION=1` planned   |
| TR-018 | Poetry + entry points                | Must     | **Met**     | `truenas-mcp`, `truenas-mcp-smoke`            |
| TR-019 | Document tested TrueNAS version      | Should   | **Doc**     | `TNAS_TESTED_MAJOR_VERSION` in constants      |
| TR-020 | `deploy/mcp.sh` discovery + smoke    | Must     | **Met**     | `deploy/mcp.sh`, root `pyproject.toml`        |
| TR-021 | Requirements compliance test         | Must     | **Met**     | `test_requirements_compliance.py`             |

---

## 6. Non-functional requirements

| ID      | Requirement                        | Priority | Status  | Notes                                         |
| ------- | ---------------------------------- | -------- | ------- | --------------------------------------------- |
| NFR-001 | Least-privilege API key user       | Must     | **Doc** | See API_KEY_SETUP                             |
| NFR-002 | `confirm=true` on future writes    | Must     | **Met** | `writes.py`, `ConfirmInput`                   |
| NFR-003 | Graceful partial summary on errors | Must     | **Met** | `asyncio.gather(..., return_exceptions=True)` |
| NFR-004 | Read tools — no mutating methods   | Must     | **Met** | Write tools classified separately             |
| NFR-005 | Poll interval guidance (≥2–5s)     | Should   | **Doc** | README; no built-in poller                    |
| NFR-006 | JSON audit logs to stderr          | Should   | **Met** | `logging_config.py`                           |
| NFR-007 | WebSocket ping/keepalive           | Could    | **Met** | `TRUENAS_WS_PING_INTERVAL_SEC`                |

---

## 7. Tool catalog (v0.2)

### Read tools

| Tool                          | Class | TrueNAS method(s)                       | Runbook ref                      |
| ----------------------------- | ----- | --------------------------------------- | -------------------------------- |
| `truenas_get_system_info`     | read  | `system.info`, `system.state`           | TIPSNTRICKS § TrueNAS monitoring |
| `truenas_check_api_key`       | read  | `system.state`, `system.info`           | API_KEY_SETUP                    |
| `truenas_list_alerts`         | read  | `alert.list`                            | TIPSNTRICKS § monitoring         |
| `truenas_list_alert_policies` | read  | `alert.list_policies`                   | TIPSNTRICKS § monitoring         |
| `truenas_list_pools`          | read  | `pool.query`                            | TIPSNTRICKS § pools              |
| `truenas_list_datasets`       | read  | `pool.dataset.query`                    | `default.truenas.nfs.env`        |
| `truenas_list_disks`          | read  | `disk.query`, `disk.temperature_alerts` | TIPSNTRICKS § Scrutiny           |
| `truenas_list_smart_results`  | read  | `smart.test.results`                    | TIPSNTRICKS § Scrutiny           |
| `truenas_get_reporting_data`  | read  | `reporting.get_data`                    | TIPSNTRICKS § monitoring         |
| `truenas_list_apps`           | read  | `app.query`                             | TIPSNTRICKS § Scrutiny           |
| `truenas_list_jobs`           | read  | `core.get_jobs`                         | TIPSNTRICKS                      |
| `truenas_list_nfs_shares`     | read  | `sharing.nfs.query`                     | TIPSNTRICKS § Path B HA          |
| `truenas_list_scrub_tasks`    | read  | `pool.scrub.query`                      | TIPSNTRICKS § pools              |
| `truenas_system_summary`      | read  | aggregate                               | TIPSNTRICKS § Path B             |
| `truenas_run_smoke_tests`     | read  | smoke                                   | SMOKE_TESTS.md                   |

### Write tools (gated)

| Tool                       | Class | TrueNAS method(s)     | Notes          |
| -------------------------- | ----- | --------------------- | -------------- |
| `truenas_create_dataset`   | write | `pool.dataset.create` | `confirm=true` |
| `truenas_update_nfs_share` | write | `sharing.nfs.update`  | `confirm=true` |
| `truenas_dismiss_alert`    | write | `alert.dismiss`       | `confirm=true` |

---

## 8. Backlog — check, update, optimize

### 8.1 Should implement (v1.1)

| Item                                      | Rationale                              |
| ----------------------------------------- | -------------------------------------- |
| `truenas_check_api_key` standalone tool   | Parity with `pve_check_token`          |
| `smart.test.results` read tool            | Pre-failure disk detection             |
| `TRUENAS_INTEGRATION=1` pytest suite      | Live lab validation in CI optional job |
| `docs/SMOKE_TESTS.md`                     | Parity with proxmox-ve-mcp             |
| Pydantic `schemas.py` for tool inputs     | Parity with sibling MCPs               |
| Explicit WebSocket ping / stale detection | Long-lived Cursor sessions             |
| Job poll helper for future writes         | `core.get_jobs` tracking pattern       |

### 8.2 Optimizations (client)

| Item                      | Current                    | Target                                     |
| ------------------------- | -------------------------- | ------------------------------------------ |
| Response matching         | Single `recv()`            | Loop until matching `id` (**done in 0.1**) |
| Reconnect                 | Reset on error             | Exponential backoff + auto-reconnect       |
| Query filters             | Raw `[]` params            | Pass filters/options for large datasets    |
| Dataset capacity warnings | Heuristic on `used.parsed` | Use `used.percentage` or documented fields |

### 8.3 Documentation / repo hygiene

| Item                                                     | Status              |
| -------------------------------------------------------- | ------------------- |
| `docs/REQUIREMENTS.md`                                   | **Met** (this file) |
| `docs/API_KEY_SETUP.md`                                  | **Met**             |
| Root `pyproject.toml` `testpaths` includes truenas tests | **Met**             |
| `mcp/README.md` truenas smoke in quick install           | Update recommended  |
| Repo map / skill reference truenas-mcp                   | Update recommended  |

### 8.4 Open questions

| ID   | Question                                      | Default assumption                                |
| ---- | --------------------------------------------- | ------------------------------------------------- |
| OQ-1 | Target TrueNAS version in lab?                | SCALE **25.10+** (`TNAS_TESTED_MAJOR_VERSION=25`) |
| OQ-2 | Keep papita MCP vs switch to official binary? | Keep papita for repo integration                  |
| OQ-3 | Read-only forever or gated NFS/share writes?  | Read-only until v2 RFC                            |
| OQ-4 | `TRUENAS_HOST` IP-only vs hostname?           | Both allowed (Tailscale DNS)                      |

---

## 9. Revision history

| Version | Date       | Changes                                                                          |
| ------- | ---------- | -------------------------------------------------------------------------------- |
| 0.1     | 2026-06-16 | Initial requirements from v0.1.0a1 implementation + lab discovery                |
| 0.2     | 2026-06-16 | v1.1 read tools, v2 gated writes, Scrutiny/Uptime Kuma lab split, SMOKE_TESTS.md |
