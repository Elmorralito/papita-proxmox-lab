# Proxmox VE MCP Server — Requirements & Traceability

**Project:** `papita-proxmox-lab` / `mcp/proxmox-ve-mcp`
**Package version:** 0.1.0a3
**Requirements version:** 0.1
**Date:** 2026-06-09
**Status:** v1 implemented

**Automated compliance checks:** `tests/test_requirements_compliance.py`

**Traceability legend:** **Met** | **Partial** | **N/A** (won't/deferred) | **Doc** (documented only)

Onboarding, architecture, and sprint history: [README.md](./README.md).

---

## 1. Executive summary

- **Goal:** Provide a typed, agent-friendly MCP server so Cursor and other AI tools can inspect and safely operate a **Proxmox VE cluster** without ad-hoc SSH shell strings.
- **Context:** This lab automates PVE via Bash (`deploy/proxmox.sh`) over SSH, using `pvesh`, `pvecm`, `pvenode`, and `ceph` on nodes. Access is typically over **Tailscale** to HTTPS **:8006** with optional pfSense LAN routing.
- **Gap:** Bash scripts require SSH keys/passwords, multiplexed sessions, and manual `jq` parsing. Agents need structured JSON tool responses, explicit safety classes, and REST API tokens decoupled from interactive SSH.
- **v1 delivery:** Python MCP server using **PVE API tokens** against any online cluster member. **15 read** tools + **3 write** tools (with `confirm=true`); **zero destructive** tools; Ceph/cluster infra mutations excluded.
- **Auth:** Dedicated API token user `@pam` with least-privilege role — not password + 2FA session tickets.
- **Safety:** Every write tool requires explicit `confirm: true`; audit log to stderr with redacted secrets.

---

## 2. Discovery findings

### 2.1 Existing automation inventory

| Source                 | Operation                   | Mechanism                                                                | Read / Write / Destructive | API mapping                                               |
| ---------------------- | --------------------------- | ------------------------------------------------------------------------ | -------------------------- | --------------------------------------------------------- |
| `deploy/proxmox.sh`    | List online cluster nodes   | SSH → `pvesh get /cluster/resources --type node`                         | Read                       | `GET /cluster/resources?type=node`                        |
| `deploy/proxmox.sh`    | Local node name             | SSH → `pvecm nodes` (parse `(local)`)                                    | Read                       | `GET /cluster/config/nodes` + hostname match              |
| `deploy/proxmox.sh`    | Cluster node config (ring0) | SSH → `pvesh get /cluster/config/nodes`                                  | Read                       | `GET /cluster/config/nodes`                               |
| `deploy/proxmox.sh`    | Cluster temperature         | SSH per-node → `sensors -j`                                              | Read                       | **No PVE REST** — SSH/exec only                           |
| `deploy/proxmox.sh`    | Start cluster (WoL)         | SSH → `pvenode wakeonlan <node>`                                         | Write                      | **No REST** — CLI only                                    |
| `deploy/proxmox.sh`    | Stop cluster                | SSH → `pvesh create /nodes/{n}/stopall`, `.../status --command shutdown` | Write / Destructive        | `POST /nodes/{node}/stopall`, `POST /nodes/{node}/status` |
| `deploy/proxmox.sh`    | Setup node                  | SCP + interactive `setup-pve-node.sh`                                    | Destructive / config       | Out of MCP v1                                             |
| `post-startup-proc.sh` | Quorum wait                 | `pvecm status` grep                                                      | Read                       | Indirect — cluster quorum via API status                  |
| `post-startup-proc.sh` | Ceph unset noout            | `ceph osd unset noout`                                                   | Write                      | Ceph CLI — not PVE API                                    |
| `pre-shutdown-proc.sh` | Stop all guests             | `pvesh stopall`                                                          | Write                      | `POST /nodes/{node}/stopall` (local)                      |
| `pre-shutdown-proc.sh` | Ceph set noout              | `ceph osd set noout`                                                     | Write                      | Ceph CLI                                                  |
| `setup-pve-node.sh`    | Mail options                | `pvesh set /cluster/options --mailto ...`                                | Write                      | `PUT /cluster/options`                                    |
| `docs/TIPSNTRICKS.md`  | Cluster verify              | `pvecm status`, `corosync-cfgtool`, `pvesh get /cluster/resources`       | Read                       | Mixed CLI + REST                                          |
| `docs/TIPSNTRICKS.md`  | OSD startup sequence        | `ceph health`, systemctl restarts                                        | Write / Destructive        | Ceph + systemd — out of v1                                |
| `docs/TIPSNTRICKS.md`  | Remove node                 | `pvecm delnode`, Ceph teardown                                           | Destructive                | Out of v1                                                 |
| `docs/TIPSNTRICKS.md`  | Storage pools               | `pvesm status`, `pvesm remove`                                           | Read / Destructive         | `GET /storage`, destructive out of v1                     |

### 2.2 Access patterns

```text
Workstation (Cursor / deploy scripts)
    │
    ├── SSH :22 ──► any cluster member (ControlMaster multiplex)
    │                 └── pvesh / pvecm / pvenode / ceph / sensors (on-node CLI)
    │
    └── HTTPS :8006 ──► Proxmox API (Tailscale MagicDNS or LAN via pfSense route)
                          └── MCP entry point (PVEAPIToken)
```

**Implication:** MCP prefers **HTTPS REST** to `:8006`. Operations with **no REST equivalent** stay in Bash or require a future **SSH proxy tool** (v2).

### 2.3 Personas

| Persona               | Goals                                                     | Primary sources                                     |
| --------------------- | --------------------------------------------------------- | --------------------------------------------------- |
| **Operator**          | Ceph health, quorum, OSD startup, safe shutdown           | `docs/TIPSNTRICKS.md`                               |
| **Deploy engineer**   | Node setup, cluster start/stop, temperatures              | `deploy/proxmox.sh`, `setup-pve-node.sh`            |
| **Troubleshooter**    | Node/guest status, tasks, logs, storage                   | PVE API `/cluster/resources`, `/nodes/{node}/tasks` |
| **AI agent (Cursor)** | Answer questions, suggest runbook steps, read-only checks | MCP read tools + runbook refs                       |

### 2.4 Gaps MCP fills vs Bash

| Gap                      | MCP benefit                                             |
| ------------------------ | ------------------------------------------------------- |
| Unstructured SSH output  | JSON schema per tool; predictable fields for agents     |
| Password / 2FA on SSH    | API token with scoped role; no TOTP on unattended calls |
| Agent invokes wrong node | Single `PVE_HOST` entry + explicit `node` parameter     |
| Destructive ops          | Tool metadata (`tool_class`) + mandatory `confirm`      |
| Discoverability          | Tool catalog + `meta.runbook_ref` preconditions         |

### 2.5 API access models

| Model                                                   | v1?                          |
| ------------------------------------------------------- | ---------------------------- |
| **API token** (`PVEAPIToken=USER@REALM!TOKENID=SECRET`) | **Yes — primary**            |
| Ticket + CSRF (username/password)                       | No — breaks with 2FA         |
| SSH + `pvesh` on jump host                              | v2 optional (`pve_ssh_exec`) |
| Root SSH direct                                         | No                           |

---

## 3. Business requirements

| ID     | Requirement                                               | Priority | Acceptance criteria                                 | Status  | Evidence                                                       |
| ------ | --------------------------------------------------------- | -------- | --------------------------------------------------- | ------- | -------------------------------------------------------------- |
| BR-001 | Enable AI agents to **inspect** cluster state without SSH | Must     | List nodes, guests, storage via JSON tools          | **Met** | `pve_list_nodes`, `pve_list_guests`, `pve_list_storage`        |
| BR-002 | **Classify** tools as read / write / destructive          | Must     | Every tool declares safety class; no destructive v1 | **Met** | `ToolClass` in `registry.py`; `meta.tool_class`; 0 destructive |
| BR-003 | Align with **existing lab workflows**                     | Must     | Each v1 tool maps to repo workflow (§7.4)           | **Met** | `RUNBOOK_REFS`, tool docstrings                                |
| BR-004 | **Tailscale** hostname to `:8006`                         | Must     | Config via `PVE_HOST`; TLS verify configurable      | **Met** | `config.py`, `PVE_VERIFY_SSL`                                  |
| BR-005 | Do **not** replace bootstrap or Terraform                 | Won't    | `setup-node` and `terraform.sh` remain              | **N/A** | `BASH_ONLY_WORKFLOWS` in `pve_cluster_health`                  |
| BR-006 | **Audit trail** for mutating invocations                  | Should   | Structured logs: tool, node, vmid, outcome          | **Met** | `write_tool_handler` → JSON stderr                             |
| BR-007 | **Revocable** automation access                           | Must     | Token rotation documented; no root in config        | **Doc** | `docs/PVE_TOKEN_SETUP.md`                                      |
| BR-008 | Faster incident diagnosis                                 | Should   | Resources, tasks, health in one session             | **Met** | `pve_cluster_health`, `pve_list_tasks`, `pve_list_resources`   |
| BR-009 | Complement Bash for WoL/sensors                           | Could    | Document Bash-only gaps                             | **Met** | `BASH_ONLY_WORKFLOWS`; no MCP tools                            |
| BR-010 | **Papita conventions** (node names, paths)                | Must     | Examples use `pvenode-001` style                    | **Met** | Tests, docs, node regex                                        |

---

## 4. Functional requirements

### 4.1 Cluster introspection

| ID     | Requirement                       | Priority | API / source                         | Status      | Evidence / notes                                           |
| ------ | --------------------------------- | -------- | ------------------------------------ | ----------- | ---------------------------------------------------------- |
| FR-001 | List cluster members with status  | Must     | `GET /cluster/resources?type=node`   | **Met**     | `pve_list_nodes`                                           |
| FR-002 | Cluster config nodes (ring0_addr) | Must     | `GET /cluster/config/nodes`          | **Met**     | `pve_get_cluster_config_nodes`; includes `api_entry_host`  |
| FR-003 | List all cluster resources        | Must     | `GET /cluster/resources`             | **Met**     | `pve_list_resources`; filters + `start`/`limit`            |
| FR-004 | Proxmox/datacenter version        | Must     | `GET /version`                       | **Met**     | `pve_get_version`                                          |
| FR-005 | Read cluster options              | Should   | `GET /cluster/options`               | **Met**     | `pve_get_cluster_options`                                  |
| FR-006 | Cluster health summary            | Must     | Derived from FR-001/002              | **Partial** | `pve_cluster_health`; approximate quorum only (no `pvecm`) |
| FR-007 | List cluster tasks                | Should   | `GET /cluster/tasks`                 | **Met**     | `pve_list_tasks`; `statusfilter` + pagination              |
| FR-008 | Task log by UPID                  | Should   | `GET /nodes/{node}/tasks/{upid}/log` | **Met**     | `pve_get_task_log`; UPID validated                         |

### 4.2 Node & guests

| ID     | Requirement                    | Priority | API / source                      | Status  | Evidence / notes                                                |
| ------ | ------------------------------ | -------- | --------------------------------- | ------- | --------------------------------------------------------------- |
| FR-010 | Node status (CPU, mem, uptime) | Must     | `GET /nodes/{node}/status`        | **Met** | `pve_get_node_status`                                           |
| FR-011 | List guests on a node          | Must     | `GET /nodes/{node}/qemu` + `/lxc` | **Met** | `pve_list_guests`, `pve_get_guest_status`; unified `guest_type` |
| FR-012 | Guest config read (redacted)   | Should   | `GET .../config`                  | **Met** | `pve_get_guest_config`; redacts secrets                         |
| FR-013 | Subscription warnings          | Could    | `GET /nodes/{node}/subscription`  | **N/A** | v2                                                              |
| FR-020 | Start VM or CT                 | Should   | `POST .../status/start`           | **Met** | `pve_start_guest`; `confirm=true`, UPID poll optional           |
| FR-021 | Stop VM or CT (ACPI)           | Should   | `POST .../status/shutdown`        | **Met** | `pve_shutdown_guest`                                            |
| FR-022 | Hard stop                      | Could    | `POST .../status/stop`            | **N/A** | v2                                                              |
| FR-023 | Migrate guest                  | Could    | `POST .../migrate`                | **N/A** | v2                                                              |
| FR-024 | Stop all guests on a node      | Should   | `POST /nodes/{node}/stopall`      | **Met** | `pve_stopall_guests`; runbook in `meta.runbook_ref`             |

### 4.3 Storage & Ceph

| ID     | Requirement                        | Priority | API / source                    | Status  | Evidence / notes                               |
| ------ | ---------------------------------- | -------- | ------------------------------- | ------- | ---------------------------------------------- |
| FR-030 | List storage definitions and usage | Must     | `GET /storage`, node storage    | **Met** | `pve_list_storage`                             |
| FR-031 | Storage status per node            | Should   | `GET /nodes/{node}/storage/...` | **Met** | Extended `pve_list_storage` with `node` param  |
| FR-040 | Ceph status summary                | Should   | Cluster or node ceph path       | **Met** | `pve_get_ceph_status`; cluster + node fallback |
| FR-041 | List Ceph OSDs                     | Should   | `GET /nodes/{node}/ceph/osd`    | **Met** | `pve_list_ceph_osds`                           |
| FR-042 | OSD runbook as non-executable ref  | Must     | Link to TIPSNTRICKS             | **Met** | `meta.runbook_ref`; no Ceph mutations          |

### 4.4 Out of scope (v1)

| ID     | Requirement                          | Priority | Rationale               | Status  |
| ------ | ------------------------------------ | -------- | ----------------------- | ------- |
| FR-900 | Node bootstrap                       | Won't    | Interactive 17-step TTY | **N/A** |
| FR-901 | `pvecm add` / `delnode`              | Won't    | Destructive             | **N/A** |
| FR-902 | Corosync config edit                 | Won't    | Manual runbook          | **N/A** |
| FR-903 | Ceph noout / OSD restart / disk wipe | Won't    | Data integrity risk     | **N/A** |
| FR-904 | Wake-on-LAN                          | Won't    | No REST                 | **N/A** |
| FR-905 | lm-sensors / `get-temp`              | Won't    | No REST                 | **N/A** |
| FR-906 | Subscription nag patch               | Won't    | setup step 15           | **N/A** |
| FR-907 | Terraform / AWS EFS                  | Won't    | Separate toolchain      | **N/A** |
| FR-908 | Storage delete                       | Won't    | Destructive             | **N/A** |

Documented in README + `BASH_ONLY_WORKFLOWS`.

---

## 5. Technical requirements

| ID     | Requirement                                 | Priority | Status  | Evidence                                |
| ------ | ------------------------------------------- | -------- | ------- | --------------------------------------- |
| TR-001 | Python 3.11+ with official `mcp` SDK        | Must     | **Met** | FastMCP in `server.py`                  |
| TR-002 | stdio transport for Cursor                  | Must     | **Met** | `run_stdio_async()`                     |
| TR-003 | `httpx` async; 30s / 120s timeouts          | Must     | **Met** | `client/http.py`                        |
| TR-004 | `PVEAPIToken` auth header                   | Must     | **Met** | `PveSettings.authorization_header()`    |
| TR-005 | `PVE_HOST`, `PVE_PORT` default 8006         | Must     | **Met** | `config.py`                             |
| TR-006 | `PVE_VERIFY_SSL` configurable               | Should   | **Doc** | `.env.example`, `PVE_TOKEN_SETUP.md`    |
| TR-007 | API prefix `/api2/json`                     | Must     | **Met** | `constants.API_PREFIX`                  |
| TR-008 | Map HTTP/PVE errors to tool errors          | Must     | **Met** | `PveApiError`                           |
| TR-009 | Tool naming `pve_*` snake_case              | Must     | **Met** | All tools in `register.py`              |
| TR-010 | Pydantic v2 input validation                | Must     | **Met** | `schemas.py`, `parse_model()`           |
| TR-011 | Pagination `start`/`limit`                  | Could    | **Met** | `pve_list_resources`, `pve_list_tasks`  |
| TR-012 | Task polling helper                         | Should   | **Met** | `client/tasks.py`                       |
| TR-013 | Secrets from env only; never log token      | Must     | **Met** | `config.py`, logging                    |
| TR-014 | Optional `.env` via dotenv                  | Could    | **Doc** | `load_dotenv()` in `server.py`          |
| TR-015 | Single `PVE_HOST`; node param on multi-node | Must     | **Met** | Design + tool inputs                    |
| TR-016 | Least-privilege role documentation          | Must     | **Doc** | `docs/PVE_TOKEN_SETUP.md`               |
| TR-017 | pytest + respx; integration flag            | Should   | **Met** | `tests/`; `PVE_INTEGRATION=1`           |
| TR-018 | Poetry package; entry point                 | Must     | **Met** | `proxmox-ve-mcp` script                 |
| TR-019 | Document tested PVE major (8.x)             | Should   | **Doc** | `PVE_TESTED_MAJOR_VERSION` in constants |

### 5.1 Suggested PVE role for MCP token

| Permission     | Path                       | Tools              |
| -------------- | -------------------------- | ------------------ |
| `Sys.Audit`    | `/`                        | All read tools     |
| `VM.Audit`     | `/vms`                     | Guest read         |
| `VM.PowerMgmt` | `/vms/{vmid}` or `/` (lab) | start/stop/stopall |

Create `mcp-agent@pam` with API token — **do not** use `root@pam`. See [docs/PVE_TOKEN_SETUP.md](./docs/PVE_TOKEN_SETUP.md).

---

## 6. Non-functional requirements

| ID      | Requirement                            | Priority | Status      | Evidence                                            |
| ------- | -------------------------------------- | -------- | ----------- | --------------------------------------------------- |
| NFR-001 | Least privilege token; no root         | Must     | **Doc**     | Token setup guide                                   |
| NFR-002 | Mutating tools require `confirm: true` | Must     | **Met**     | `require_confirm()`, `ConfirmWriteInput`            |
| NFR-003 | Graceful partial data when not quorate | Must     | **Met**     | Warnings in health, guests, storage, ceph           |
| NFR-004 | Idempotent read tools (GET only)       | Must     | **Met**     | By design                                           |
| NFR-005 | p95 read latency < 5s (lab scale)      | Should   | **Met**     | Semaphore max 4 concurrent HTTP                     |
| NFR-006 | JSON logs to stderr                    | Should   | **Met**     | `logging_config.py`                                 |
| NFR-007 | Tool descriptions cite runbooks        | Should   | **Met**     | `RUNBOOK_REFS`, `meta.runbook_ref`                  |
| NFR-008 | Repo Python style (black 120, isort)   | Should   | **Partial** | Root `pyproject.toml`; MCP path pre-commit optional |
| NFR-009 | Cursor MCP compatibility               | Must     | **Manual**  | Smoke test checklist in README                      |
| NFR-010 | README + `.env.example` + `mcp.json`   | Must     | **Met**     | Package docs                                        |

---

## 7. MCP tool catalog

### 7.1 v1 read tools

| Tool                           | Class | PVE endpoint                         | MCP tool |
| ------------------------------ | ----- | ------------------------------------ | -------- |
| `pve_get_version`              | read  | `GET /version`                       | ✓        |
| `pve_list_nodes`               | read  | `GET /cluster/resources?type=node`   | ✓        |
| `pve_get_cluster_config_nodes` | read  | `GET /cluster/config/nodes`          | ✓        |
| `pve_cluster_health`           | read  | derived                              | ✓        |
| `pve_list_resources`           | read  | `GET /cluster/resources`             | ✓        |
| `pve_get_node_status`          | read  | `GET /nodes/{node}/status`           | ✓        |
| `pve_list_guests`              | read  | qemu + lxc lists                     | ✓        |
| `pve_get_guest_status`         | read  | `GET .../status/current`             | ✓        |
| `pve_get_guest_config`         | read  | `GET .../config`                     | ✓        |
| `pve_list_storage`             | read  | `GET /storage`, node storage         | ✓        |
| `pve_list_tasks`               | read  | `GET /cluster/tasks`                 | ✓        |
| `pve_get_task_log`             | read  | `GET /nodes/{node}/tasks/{upid}/log` | ✓        |
| `pve_get_cluster_options`      | read  | `GET /cluster/options`               | ✓        |
| `pve_get_ceph_status`          | read  | cluster or node ceph path            | ✓        |
| `pve_list_ceph_osds`           | read  | `GET /nodes/{node}/ceph/osd`         | ✓        |

### 7.2 v1 write tools

| Tool                 | Class | PVE endpoint                 | Safety gate                           |
| -------------------- | ----- | ---------------------------- | ------------------------------------- |
| `pve_start_guest`    | write | `POST .../status/start`      | `confirm=true` required               |
| `pve_shutdown_guest` | write | `POST .../status/shutdown`   | `confirm=true` required               |
| `pve_stopall_guests` | write | `POST /nodes/{node}/stopall` | `confirm=true` + Ceph runbook warning |

### 7.3 v2 backlog

| Tool                                           | Class       | Notes                                               |
| ---------------------------------------------- | ----------- | --------------------------------------------------- |
| `pve_migrate_guest`                            | write       | FR-023                                              |
| `pve_create_snapshot`                          | write       | Backup workflows                                    |
| `pve_ssh_exec_read`                            | read        | SSH proxy for sensors/Ceph CLI — allowlist required |
| `pve_wake_on_lan`                              | write       | Wrap `pvenode wakeonlan`                            |
| `pve_shutdown_node`                            | destructive | Maps `stop-cluster`                                 |
| `pve_get_firewall_rules`                       | read        | Cluster firewall step 14                            |
| MCP resource `runbook://tipsntricks/{section}` | read        | TIPSNTRICKS sections for agents                     |

### 7.4 Mapping to repo workflows

| Repo workflow                       | MCP v1 coverage                                          |
| ----------------------------------- | -------------------------------------------------------- |
| `./deploy/proxmox.sh cluster-nodes` | `pve_list_nodes`                                         |
| `./deploy/proxmox.sh local-node`    | `pve_get_cluster_config_nodes` + `api_entry_host` hint   |
| `./deploy/proxmox.sh get-temp`      | **Not covered** — Bash                                   |
| `./deploy/proxmox.sh start-cluster` | **Not covered** — Bash                                   |
| `./deploy/proxmox.sh stop-cluster`  | Partial — `pve_stopall_guests` only                      |
| TIPSNTRICKS cluster verify          | `pve_cluster_health`, `pve_list_nodes`, `pve_list_tasks` |
| TIPSNTRICKS OSD startup             | Runbook reference only (FR-042)                          |
| `pre-shutdown-proc.sh` stopall      | `pve_stopall_guests`                                     |

---

## 8. Resolved design decisions

| #    | Question                              | Decision                              | Impact                               |
| ---- | ------------------------------------- | ------------------------------------- | ------------------------------------ |
| OQ-1 | `PVE_HOST` — main only or any member? | **Any online member**                 | Matches `deploy/proxmox.sh -ip`      |
| OQ-2 | SSH proxy in v1?                      | **No — v2**                           | FR-904/905 stay Bash-only            |
| OQ-3 | Guest power in lab?                   | **Yes with confirm**                  | Read-only token omits `VM.PowerMgmt` |
| OQ-4 | TIPSNTRICKS as MCP resources?         | **Docstrings v1; resources v2**       | `RUNBOOK_REFS` dict                  |
| OQ-5 | Python vs TypeScript?                 | **Python**                            | Aligns with repo tooling             |
| OQ-6 | Self-signed TLS before step 17?       | **`PVE_VERIFY_SSL=false` documented** | `.env.example` comments              |
| OQ-7 | Concurrent HTTP limit?                | **Semaphore max 4**                   | `client/http.py`                     |

---

## 9. Gaps remaining (non-blocking)

| Item                            | Priority          | Action                                |
| ------------------------------- | ----------------- | ------------------------------------- |
| NFR-008 pre-commit path for MCP | Could             | Add to root `.pre-commit-config.yaml` |
| NFR-009 Cursor manual QA        | Manual            | Operator sign-off                     |
| FR-006 true quorum              | Partial by design | v2 SSH/`pvecm` proxy if needed        |
| MCP resources for TIPSNTRICKS   | v2                | OQ-4                                  |

---

## Appendix A — Proxmox REST reference

| Method | Path                                               | Requirement    |
| ------ | -------------------------------------------------- | -------------- |
| GET    | `/api2/json/version`                               | FR-004         |
| GET    | `/api2/json/cluster/resources`                     | FR-001, FR-003 |
| GET    | `/api2/json/cluster/config/nodes`                  | FR-002         |
| GET    | `/api2/json/cluster/options`                       | FR-005         |
| GET    | `/api2/json/cluster/tasks`                         | FR-007         |
| GET    | `/api2/json/nodes/{node}/status`                   | FR-010         |
| GET    | `/api2/json/nodes/{node}/qemu`                     | FR-011         |
| GET    | `/api2/json/nodes/{node}/lxc`                      | FR-011         |
| POST   | `/api2/json/nodes/{node}/stopall`                  | FR-024         |
| POST   | `/api2/json/nodes/{node}/qemu/{vmid}/status/start` | FR-020         |

Official docs: [Proxmox VE API](https://pve.proxmox.com/pve-docs/pve-admin-guide.html#chapter_pve_api).

## Appendix B — Repository file index

| Path                            | Relevance                               |
| ------------------------------- | --------------------------------------- |
| `docs/TIPSNTRICKS.md`           | Runbooks, cluster troubleshooting, Ceph |
| `deploy/proxmox.sh`             | SSH automation, pvesh patterns          |
| `src/bash/post-startup-proc.sh` | Quorum, Ceph noout unset, WoL           |
| `src/bash/pre-shutdown-proc.sh` | stopall, Ceph noout set                 |
| `src/bash/setup-pve-node.sh`    | Out-of-scope bootstrap                  |

---

_Requirements & traceability v0.1 — package 0.1.0a3 — audited 2026-06-09._
