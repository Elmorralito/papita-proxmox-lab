# pfSense REST API MCP Server — Requirements & Traceability

**Project:** `papita-proxmox-lab` / `mcp/pfsense-mcp`
**Package version:** 0.1.0a1
**Requirements version:** 0.2
**Date:** 2026-06-11
**Status:** v1 read-only implemented

**Automated compliance checks:** `tests/test_requirements_compliance.py`

**Traceability legend:** **Met** | **Partial** | **N/A** (won't/deferred) | **Doc** (documented only)

Onboarding and sprint plan: [README.md](../README.md), [IMPLEMENTATION.md](./IMPLEMENTATION.md).

---

## 1. Executive summary

- **Goal:** Typed MCP server so agents **inspect** pfSense in this lab without WebGUI or ad-hoc shell.
- **API:** Community [pfREST v2](https://pfrest.org/) at `/api/v2`; unofficial — not Netgate-supported.
- **v1 delivered:** **Read-only** — 6 MCP tools, zero write tools (writes deferred to v1.1 per [IMPLEMENTATION.md](./IMPLEMENTATION.md)).
- **Auth:** `X-API-Key`; `PFSENSE_HOST` = **IPv4/IPv6 literal only** (lab default `172.16.0.1`).
- **Safety:** All v1 tools are `read`; `require_confirm()` scaffold present for v1.1 writes.

---

## 2. Discovery findings

Unchanged from v0.1-draft — see git history. **Access note (resolved):** `PFSENSE_HOST` is IP-only, not MagicDNS (OQ-1).

---

## 3. Business requirements

| ID     | Requirement                               | Priority | Acceptance criteria                                      | Status      | Evidence                                                                                                    |
| ------ | ----------------------------------------- | -------- | -------------------------------------------------------- | ----------- | ----------------------------------------------------------------------------------------------------------- |
| BR-001 | Agents **inspect** pfSense without WebGUI | Must     | Interfaces, firewall, routes, system info via JSON tools | **Met**     | `pfs_list_interfaces`, `pfs_list_firewall_rules`, `pfs_system_summary` (routes/gateways), `pfs_get_version` |
| BR-002 | **Classify** tools read/write/destructive | Must     | Every tool declares class; no destructive v1             | **Met**     | `ToolClass`, `TOOL_REGISTRY`; compliance test                                                               |
| BR-003 | Align with **lab workflows**              | Must     | Maps to `tailscale-pfsense-lan.sh verify`, TIPSNTRICKS   | **Met**     | Tailscale + LAN checks; `RUNBOOK_REFS`                                                                      |
| BR-004 | Reach pfSense over LAN/Tailscale          | Must     | `PFSENSE_HOST`; TLS configurable                         | **Met**     | `config.py`; IP validator; `PFSENSE_VERIFY_SSL`                                                             |
| BR-005 | Do **not** replace Tailscale Admin API    | Won't    | Bash script remains                                      | **N/A**     | `OUT_OF_SCOPE_V1`                                                                                           |
| BR-006 | **Audit trail** for mutating calls        | Should   | Structured logs; no secrets                              | **N/A**     | v1 read-only; v1.1 writes                                                                                   |
| BR-007 | **Revocable** automation access           | Must     | Dedicated user + rotation doc                            | **Doc**     | `PFSENSE_API_KEY_SETUP.md`                                                                                  |
| BR-008 | Faster incident diagnosis                 | Should   | Interfaces, gateways, Tailscale in one session           | **Partial** | `pfs_system_summary`; no logs (FR-050 v1.1)                                                                 |
| BR-009 | Complement Proxmox MCP                    | Should   | Correlate PVE reachability                               | **Met**     | `proxmox_hint` in summary meta                                                                              |
| BR-010 | **Papita conventions**                    | Must     | `172.16.0.0/16`, `pfsense-fw001`                         | **Met**     | `constants.py`                                                                                              |
| BR-011 | Acknowledge **unofficial** API            | Must     | README + upgrade caveats                                 | **Met**     | README disclaimer; `PFS_TESTED_MAJOR_VERSION`                                                               |

---

## 4. Functional requirements

### 4.1 System & package

| ID     | Requirement               | Priority | API / source                   | Status      | Evidence                                                 |
| ------ | ------------------------- | -------- | ------------------------------ | ----------- | -------------------------------------------------------- |
| FR-001 | pfSense / package version | Must     | `GET /system/version`          | **Met**     | `pfs_get_version`                                        |
| FR-002 | REST API settings read    | Must     | `GET /system/restapi/settings` | **Partial** | Smoke + `pfs_system_summary.restapi`; no standalone tool |
| FR-003 | Hostname, domain, time    | Should   | From version payload           | **Partial** | `pfs_system_summary.system` identity fields              |
| FR-004 | Health / status summary   | Must     | Derived                        | **Met**     | `pfs_system_summary`                                     |
| FR-005 | List installed packages   | Should   | Package manager                | **N/A**     | v1.1                                                     |

### 4.2 Interfaces & routing

| ID     | Requirement           | Priority | API / source             | Status      | Evidence                                   |
| ------ | --------------------- | -------- | ------------------------ | ----------- | ------------------------------------------ |
| FR-010 | List interfaces       | Must     | `/interfaces`            | **Met**     | `pfs_list_interfaces`                      |
| FR-011 | Interface assignments | Should   | Assignments endpoint     | **N/A**     | v1.1                                       |
| FR-020 | List static routes    | Should   | `/routing/static_routes` | **Partial** | In `pfs_system_summary.static_routes` only |
| FR-021 | List gateways         | Should   | `/routing/gateways`      | **Partial** | In `pfs_system_summary.gateways` only      |
| FR-022 | Verify LAN CIDR       | Should   | Derived                  | **Met**     | Warnings in interfaces + summary           |

### 4.3 Firewall & NAT

| ID     | Requirement                  | Priority | API / source      | Status      | Evidence                                                |
| ------ | ---------------------------- | -------- | ----------------- | ----------- | ------------------------------------------------------- |
| FR-030 | List firewall rules + filter | Must     | `/firewall/rules` | **Met**     | `pfs_list_firewall_rules`; `limit`/`offset`/`interface` |
| FR-031 | List NAT rules               | Should   | NAT endpoints     | **N/A**     | v1.1                                                    |
| FR-032 | List aliases                 | Should   | Alias endpoints   | **N/A**     | v1.1                                                    |
| FR-033 | Anti-lockout presence        | Should   | Derived           | **Partial** | `anti_lockout_present` in firewall tool; page-limited   |

### 4.4 Tailscale

| ID     | Requirement                | Priority | API / source                   | Status  | Evidence                        |
| ------ | -------------------------- | -------- | ------------------------------ | ------- | ------------------------------- |
| FR-040 | Tailscale enabled / auth   | Must     | `/services/tailscale/settings` | **Met** | `pfs_get_tailscale_status`      |
| FR-041 | Advertised `172.16.0.0/16` | Must     | Tailscale settings             | **Met** | Warnings + smoke test           |
| FR-042 | Accept subnet routes       | Should   | Tailscale settings             | **Met** | `accept_routes` field + warning |

### 4.5 Diagnostics

| ID     | Requirement    | Priority | API / source       | Status  | Evidence |
| ------ | -------------- | -------- | ------------------ | ------- | -------- |
| FR-050 | Paginated logs | Should   | Log endpoints      | **N/A** | v1.1     |
| FR-051 | Service status | Should   | Services endpoints | **N/A** | v1.1     |

### 4.6 Writes (deferred v1.1)

| ID     | Requirement            | Priority | Status  | Notes |
| ------ | ---------------------- | -------- | ------- | ----- |
| FR-060 | `dry_run` preflight    | Should   | **N/A** | v1.1  |
| FR-061 | Apply firewall changes | Should   | **N/A** | v1.1  |
| FR-062 | Toggle rule enable     | Could    | **N/A** | v1.1  |

### 4.7 Out of scope

| IDs        | Status                         |
| ---------- | ------------------------------ |
| FR-900–907 | **N/A** — documented in README |

---

## 5. Technical requirements

| ID     | Requirement                       | Priority | Status  | Evidence                                                                            |
| ------ | --------------------------------- | -------- | ------- | ----------------------------------------------------------------------------------- |
| TR-001 | Python 3.11+ + FastMCP            | Must     | **Met** | `server.py`, `pyproject.toml`                                                       |
| TR-002 | stdio transport                   | Must     | **Met** | `run_stdio_async()`                                                                 |
| TR-003 | httpx async; configurable timeout | Must     | **Met** | `PfsClient`; `PFSENSE_HTTP_TIMEOUT_SEC`                                             |
| TR-004 | `X-API-Key` auth                  | Must     | **Met** | `client/http.py`                                                                    |
| TR-005 | `PFSENSE_HOST` IP, port 443       | Must     | **Met** | `config.py` IP validator                                                            |
| TR-006 | `PFSENSE_VERIFY_SSL`              | Should   | **Met** | `config.py`, `.env.example`                                                         |
| TR-007 | `/api/v2` prefix                  | Must     | **Met** | `constants.API_PREFIX`                                                              |
| TR-008 | pfREST envelope → errors          | Must     | **Met** | `PfsApiError`, `_parse_response`                                                    |
| TR-009 | `pfs_*` tool names                | Must     | **Met** | `register.py`                                                                       |
| TR-010 | Pydantic v2 inputs                | Must     | **Met** | `schemas.py`, `parse_model`                                                         |
| TR-011 | Pagination passthrough            | Should   | **Met** | `ListFirewallRulesInput`                                                            |
| TR-012 | Query filter helpers              | Could    | **N/A** | v1.1                                                                                |
| TR-013 | Secrets from env; never log key   | Must     | **Met** | `server.py` logs host only                                                          |
| TR-014 | dotenv                            | Could    | **Met** | `load_dotenv()` in `main()`                                                         |
| TR-015 | Concurrency semaphore             | Should   | **N/A** | Deferred per IMPLEMENTATION                                                         |
| TR-016 | API key setup doc                 | Must     | **Doc** | `PFSENSE_API_KEY_SETUP.md`                                                          |
| TR-017 | pytest + respx; integration flag  | Should   | **Met** | `tests/`; `PFSENSE_INTEGRATION=1`                                                   |
| TR-018 | Poetry + entry points             | Must     | **Met** | `pfsense-mcp`, `pfsense-mcp-smoke`, `pfsense-mcp-bootstrap`, `pfsense-mcp-firewall` |
| TR-019 | Document tested versions          | Should   | **Doc** | `PFS_TESTED_MAJOR_VERSION`, README                                                  |
| TR-020 | `deploy/mcp.sh` discovery         | Must     | **Met** | root `pyproject.toml`, `mcp/README.md`                                              |
| TR-021 | `dry_run`/`apply` on writes       | Should   | **N/A** | v1.1 writes                                                                         |

---

## 6. Non-functional requirements

| ID      | Requirement               | Priority | Status      | Evidence                                                 |
| ------- | ------------------------- | -------- | ----------- | -------------------------------------------------------- |
| NFR-001 | Least privilege key       | Must     | **Doc**     | Setup guide                                              |
| NFR-002 | `confirm=true` on writes  | Must     | **N/A**     | v1 read-only; `require_confirm()` tested                 |
| NFR-003 | Graceful 403 partial data | Must     | **Met**     | `asyncio.gather(..., return_exceptions=True)` in summary |
| NFR-004 | Read tools GET-only       | Must     | **Met**     | By design                                                |
| NFR-005 | p95 read < 5s lab         | Should   | **Manual**  | Not benchmarked                                          |
| NFR-006 | JSON logs stderr          | Should   | **Partial** | Stdlib logging (v1); JSON deferred v1.1                  |
| NFR-007 | Runbook refs in tools     | Should   | **Met**     | `RUNBOOK_REFS` + `tool_meta`                             |
| NFR-008 | black/isort style         | Should   | **Partial** | Root pre-commit when touched                             |
| NFR-009 | Cursor MCP compatible     | Must     | **Manual**  | Smoke + operator sign-off                                |
| NFR-010 | README + env examples     | Must     | **Met**     | Package root files                                       |
| NFR-011 | No auth retries           | Must     | **Met**     | Single attempt in client                                 |
| NFR-012 | Redact secrets in reads   | Should   | **Met**     | `redact_sensitive()` on tool payloads                    |

---

## 7. MCP tool catalog (v1 shipped)

### 7.1 Read tools

| Tool                       | Class | pfREST / source                                          | Status  |
| -------------------------- | ----- | -------------------------------------------------------- | ------- |
| `pfs_get_version`          | read  | `/system/version`                                        | **Met** |
| `pfs_list_interfaces`      | read  | `/interfaces`                                            | **Met** |
| `pfs_get_tailscale_status` | read  | `/services/tailscale/settings`                           | **Met** |
| `pfs_system_summary`       | read  | derived (+ gateways, static routes, restapi)             | **Met** |
| `pfs_list_firewall_rules`  | read  | `/firewall/rules`                                        | **Met** |
| `pfs_verify_lab_policy`    | read  | policy registry (firewall + REST API access + endpoints) | **Met** |
| `pfs_run_smoke_tests`      | read  | smoke harness (9 checks; core exit)                      | **Met** |

### 7.2 Write tools (v1.1 backlog)

| Tool                         | Class | Notes                           |
| ---------------------------- | ----- | ------------------------------- |
| `pfs_apply_firewall_changes` | write | FR-061                          |
| `pfs_dry_run_patch`          | read  | Removed from plan — too generic |

### 7.3 Deferred standalone tools (folded or v1.1)

| Original draft tool                      | Disposition                 |
| ---------------------------------------- | --------------------------- |
| `pfs_get_restapi_settings`               | Folded into summary + smoke |
| `pfs_list_gateways` / `pfs_list_routes`  | Folded into summary         |
| `pfs_list_nat_rules`, `pfs_list_aliases` | v1.1                        |
| `pfs_query_logs`, `pfs_list_services`    | v1.1                        |

### 7.4 Repo workflow mapping

| Workflow                          | v1 coverage                                               |
| --------------------------------- | --------------------------------------------------------- |
| `tailscale-pfsense-lan.sh verify` | Partial — Tailscale + LAN via MCP; HTTPS :8006 stays Bash |
| `pfsense-steps`                   | Read tools validate post-check state                      |
| TIPSNTRICKS pfSense/Tailscale     | `RUNBOOK_REFS` links                                      |
| Proxmox admin via LAN             | Both MCP servers                                          |

---

## 8. Resolved open questions

| #    | Decision                                                        |
| ---- | --------------------------------------------------------------- |
| OQ-1 | **`PFSENSE_HOST` = IP literal only** (not MagicDNS)             |
| OQ-2 | No GraphQL in v1                                                |
| OQ-3 | Adapt proxmox patterns; simplified layout (IMPLEMENTATION v0.2) |
| OQ-4 | DHCP/DNS v1.1                                                   |
| OQ-5 | Hand-curated tools                                              |
| OQ-6 | API key only for MCP v1                                         |

---

## 9. Gaps remaining

| Item                                  | Priority | Action                                               |
| ------------------------------------- | -------- | ---------------------------------------------------- |
| Live Swagger path confirmation        | Must     | Adjust `constants.py` EP\_\* if 404                  |
| Operator Cursor sign-off              | Manual   | NFR-009                                              |
| FR-020/021 standalone list tools      | Could    | v1.1 if agents need drill-down                       |
| Write tools + audit JSON logging      | v1.1     | FR-060/061, BR-006, NFR-002                          |
| `nat_outbound` policy domain          | P2       | [POLICY.md](./POLICY.md) — Hybrid NAT Tailscale SNAT |
| `pfs_apply_firewall_policy` MCP write | P2       | v1.1 with `confirm=true`                             |

---

## Appendix A — pfREST reference

See v0.1-draft Appendix A (unchanged URLs).

## Appendix B — Repository file index

| Path                                    | Relevance                         |
| --------------------------------------- | --------------------------------- |
| `src/pfsense_mcp/tools/system.py`       | FR-001, FR-004, FR-040–042        |
| `src/pfsense_mcp/tools/network.py`      | FR-010, FR-030, FR-033            |
| `tests/test_requirements_compliance.py` | BR-002, tool catalog              |
| `deploy/tailscale-pfsense-lan.sh`       | Workflow reference (not replaced) |

---

_Requirements v0.2 — package 0.1.0a1 — audited 2026-06-11._
