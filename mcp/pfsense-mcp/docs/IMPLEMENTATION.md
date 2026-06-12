# pfSense REST API MCP Server — Implementation Strategy

**Project:** `papita-proxmox-lab` / `mcp/pfsense-mcp`
**Language:** Python 3.11+
**Strategy version:** 0.2
**Date:** 2026-06-10
**Status:** Ready for Phase A — simplified for maintainability

**Inputs:** [REQUIREMENTS.md](./REQUIREMENTS.md) · [proxmox-ve-mcp](../proxmox-ve-mcp/) (copy patterns, not file parity) · [pfREST docs](https://pfrest.org/)

**Design goal:** Smallest useful MCP — read-only v1, few modules, few tools, one doc for ops. Full requirement traceability stays in `REQUIREMENTS.md`; this file is the **build plan only**.

---

## 1. Executive summary

This document defines a **lean, three-phase** delivery plan for a Python MCP server. It copies proven patterns from `proxmox-ve-mcp` but **does not mirror its file count or tool surface**.

| Phase              | Focus                   | Delivers                                             | Est.     |
| ------------------ | ----------------------- | ---------------------------------------------------- | -------- |
| **A — Foundation** | Scaffold + HTTP client  | Runnable stdio server, config, errors, one stub tool | 1 day    |
| **B — Read v1**    | Lab-critical reads only | 6 MCP tools + aggregated summary                     | 2–3 days |
| **C — Ship**       | Docs, smoke, deploy     | README, API key guide, `deploy/mcp.sh`, pytest core  | 1–2 days |
| **v1.1+**          | Extended reads + writes | NAT, logs, services, apply, extra tools              | backlog  |

**v1 exit criteria (simplified):** 7 read tools, **zero write tools**, `./deploy/mcp.sh smoke` passes (core), Cursor MCP green, `PFSENSE_API_KEY_SETUP.md` + `POLICY.md` complete.

> **Change from v0.1:** Dropped 5-sprint / 15-tool plan. Writes (`pfs_apply_*`, `pfs_dry_run_patch`) moved to v1.1 — read-only v1 is easier to secure, test, and maintain.

---

## 1.1 Simplicity review (bottlenecks, cuts, deferrals)

Use this table when scoping work. Items marked **CUT** or **DEFER** reduce maintenance cost without blocking lab verify.

### Bottlenecks — fix or accept before coding

| ID      | Bottleneck                                                | Impact                        | Resolution                                                                                           |
| ------- | --------------------------------------------------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------- |
| **B-1** | Tailscale pfREST endpoint path unknown until live Swagger | Blocks Phase B tailscale tool | **Phase A pre-flight:** record 5–8 endpoint constants only; no OpenAPI export repo                   |
| **B-2** | Per-endpoint pfSense privileges → 403 on partial tool set | Confusing agent errors        | Single `pfs_run_smoke_tests` + setup doc; inline 403 hint in `PfsApiError` (**no** `permissions.py`) |
| **B-3** | `pfs_system_summary` parallel fetch partial failures      | Complex merge logic           | Keep summary **thin**: 3–4 GETs max; warnings not nested objects                                     |
| **B-4** | Firewall rule payloads can be huge                        | Agent context blow-up         | Default `limit=50` on `pfs_list_firewall_rules`; no unbounded list tools                             |
| **B-5** | mirroring proxmox-ve-mcp module-for-module                | 20+ files before first tool   | Copy **patterns** (client, response, register); use **3 tool modules** not 8                         |

### Components to CUT from v1

| Component                               | Was in v0.1     | Why cut                                                     |
| --------------------------------------- | --------------- | ----------------------------------------------------------- |
| `pfs_dry_run_patch`                     | Sprint 4 write  | Generic PATCH + arbitrary path = unsafe and hard to support |
| `pfs_apply_firewall_changes`            | Sprint 4 write  | Defer all writes to v1.1; read-only v1                      |
| `pfs_get_restapi_settings`              | Standalone tool | Fold check into smoke test #4 only                          |
| `pfs_check_api_key`                     | Standalone tool | Duplicate of smoke; smoke is enough                         |
| `pfs_list_aliases`                      | Sprint 2        | P2; not lab-verify critical                                 |
| `pfs_query_logs`                        | Sprint 3        | Large payloads; v1.1                                        |
| `pfs_list_services`                     | Sprint 2–3      | v1.1                                                        |
| `pfs_list_routes` / `pfs_list_gateways` | Separate tools  | **Fold into** `pfs_system_summary`                          |
| `pfs_list_nat_rules`                    | Sprint 2        | v1.1                                                        |
| `client/permissions.py`                 | Sprint 0        | One function in `errors.py` is enough                       |
| `test_requirements_compliance.py`       | Sprint 3        | Heavy; REQUIREMENTS.md is source of truth                   |
| `docs/SMOKE_TESTS.md`                   | Sprint 4        | **Section in README** until tool count grows                |
| `docs/openapi/` Swagger export          | §6              | Constants in code only; no fixture sync burden              |
| `RUNBOOK_REFS` dict                     | meta.py         | Link in tool docstrings only for v1                         |
| JSON structured logging                 | Sprint 0        | Stdlib `logging` to stderr until writes land in v1.1        |
| Semaphore (max 4)                       | TR-015          | **Defer** — single-user MCP; add if latency proves issue    |

### Components to KEEP (minimum viable)

| Component                                              | Reason                                                   |
| ------------------------------------------------------ | -------------------------------------------------------- |
| `PfsSettings` + IP-only host validator                 | BR-004; fail fast                                        |
| `PfsClient` + envelope parse                           | All tools depend on it                                   |
| `ToolClass` + `TOOL_REGISTRY`                          | BR-002; cheap safety metadata                            |
| `ok_response` / `error_response`                       | Agent JSON contract                                      |
| `require_confirm()` scaffold                           | Zero callers in v1, but 10 lines — ready for v1.1 writes |
| `pfs_run_smoke_tests` + `pfsense-mcp-smoke` CLI        | One QA surface (not three)                               |
| `test_config.py` + `test_client.py` + 1 tool test file | Core regression without compliance boilerplate           |

### Revised v1 tool catalog (7 tools)

| Tool                       | Class | Replaces (v0.1)                                                |
| -------------------------- | ----- | -------------------------------------------------------------- |
| `pfs_get_version`          | read  | same                                                           |
| `pfs_list_interfaces`      | read  | same                                                           |
| `pfs_get_tailscale_status` | read  | same                                                           |
| `pfs_system_summary`       | read  | + gateways/routes/LAN check (no separate list tools)           |
| `pfs_list_firewall_rules`  | read  | same (paginated)                                               |
| `pfs_verify_lab_policy`    | read  | policy registry — firewall + REST API access + endpoint probes |
| `pfs_run_smoke_tests`      | read  | + restapi settings check, api key check, 3 policy domains      |

**CLIs (not MCP tools):** `pfsense-mcp-bootstrap`, `pfsense-mcp-firewall` — see [POLICY.md](./POLICY.md).

**v1.1 adds:** `pfs_list_nat_rules`, `pfs_query_logs`, `pfs_apply_firewall_policy`, optional `pfs_check_api_key` if smoke insufficient.

---

## 2. Requirement analysis & prioritization

> **Note:** Full BR/FR/TR/NFR tables live in [REQUIREMENTS.md](./REQUIREMENTS.md). Below: **v1 relevance only** after simplicity review (§1.1). Deferred items are satisfied in v1.1 or by documentation.

Requirements are scored **P0** (blocking v1), **P1** (v1 should-have → mostly **DEFER v1.1** after review), **P2** (backlog).

### 2.1 Business requirements

| ID         | Priority              | Analysis                                                                                                                                                                                                                    | Sprint   |
| ---------- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| **BR-001** | **P0**                | Core value proposition. Without read tools for interfaces, firewall, routes, and system info, the MCP has no reason to exist. Drives Sprint 1–2 tool modules.                                                               | 1–2      |
| **BR-002** | **P0**                | Safety model is non-negotiable for agent-facing tools. Implement `ToolClass` enum + `TOOL_REGISTRY` identical to PVE MCP; zero `DESTRUCTIVE` in v1.                                                                         | 0        |
| **BR-003** | **P0**                | Lab alignment means `pfs_get_tailscale_status` and `pfs_system_summary` must encode checks from `tailscale-pfsense-lan.sh verify` (advertised `172.16.0.0/16`, LAN gateway). Add `meta.runbook_ref` constants.              | 1        |
| **BR-004** | **P0**                | `PfsSettings` with `PFSENSE_HOST`, port 443, `PFSENSE_VERIFY_SSL`. **`PFSENSE_HOST` must be an IPv4 or IPv6 literal** — reject hostnames and FQDNs at config load (OQ-1 resolved: always IP; lab default `172.16.0.1`).     | 0        |
| **BR-005** | N/A                   | Explicit exclusion — no code. Document in README that route approval stays in Bash.                                                                                                                                         | 4 (docs) |
| **BR-006** | ~~P1~~ **DEFER v1.1** | No write tools in v1 — audit decorator when first write lands.                                                                                                                                                              | v1.1     |
| **BR-007** | **P0**                | Cannot ship without `docs/PFSENSE_API_KEY_SETUP.md` — dedicated `mcp-cursor-agent` user, per-endpoint privileges, key rotation. Blocks operator sign-off.                                                                   | 4        |
| **BR-008** | **P1**                | `pfs_system_summary` aggregates FR-004 derived data in one call — high operator value, low extra API cost (parallel GETs).                                                                                                  | 1        |
| **BR-009** | **P1**                | Cross-MCP correlation is documentation + summary tool warnings (e.g. "verify Proxmox via proxmox-ve-mcp if LAN route OK"). No code coupling.                                                                                | 4        |
| **BR-010** | **P0**                | Constants module: `LAB_LAN_CIDR = "172.16.0.0/16"`, `LAB_PFSENSE_LAN_IP = "172.16.0.1"`, Tailscale device name `pfsense-fw001` (for cross-referencing `deploy/tailscale-pfsense-lan.sh` only — **not** for `PFSENSE_HOST`). | 0–1      |
| **BR-011** | **P0**                | README disclaimer section + TR-019 version pin. Prevents false confidence in Netgate support.                                                                                                                               | 4        |

### 2.2 Functional requirements

#### System & package (§4.1)

| ID         | Priority | Analysis                                                                                                                                                               | Sprint |
| ---------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| **FR-001** | **P0**   | First smoke-test target. Confirms API key, TLS, and package presence. Endpoint: validate against live Swagger (`GET /api/v2/system/version` or documented equivalent). | 1      |
| **FR-002** | **P0**   | Covered by smoke test #4, not a standalone tool.                                                                                                                       | B      |
| **FR-003** | **P1**   | Fold into `pfs_system_summary` or separate `pfs_get_system_info` if Swagger exposes clean endpoint. Not blocking if summary covers hostname.                           | 1      |
| **FR-004** | **P0**   | Derived tool — orchestrates parallel reads (interfaces, gateways, Tailscale, version). Maps to operator dashboard persona.                                             | 1      |
| **FR-005** | **P2**   | Nice for troubleshooting; package list endpoint may be slow. Defer to Sprint 3 unless trivial.                                                                         | 3      |

#### Interfaces & routing (§4.2)

| ID         | Priority                     | Analysis                                                                                                          | Sprint |
| ---------- | ---------------------------- | ----------------------------------------------------------------------------------------------------------------- | ------ |
| **FR-010** | **P0**                       | Lab-critical — LAN address must show `172.16.0.0/16` segment. Pagination unlikely needed (small interface count). | 1      |
| **FR-011** | ~~P1~~ **DEFER**             | Fold into `pfs_list_interfaces` response if needed.                                                               | v1.1   |
| **FR-020** | ~~P1~~ **CUT separate tool** | Data in `pfs_system_summary` only.                                                                                | B      |
| **FR-021** | ~~P1~~ **CUT separate tool** | Data in `pfs_system_summary` only.                                                                                | B      |
| **FR-022** | **P0**                       | Implement as validation inside `pfs_system_summary` / `pfs_list_interfaces` warnings, not standalone tool.        | 1      |

#### Firewall & NAT (§4.3)

| ID         | Priority              | Analysis                                         | Sprint |
| ---------- | --------------------- | ------------------------------------------------ | ------ |
| **FR-030** | **P0**                | Paginated read; default `limit=50`.              | B      |
| **FR-031** | ~~P1~~ **DEFER v1.1** | NAT rules — not needed for tailscale verify.     | v1.1   |
| **FR-032** | **P2**                | **CUT v1**                                       | —      |
| **FR-033** | ~~P1~~ **DEFER v1.1** | Anti-lockout check optional in summary warnings. | v1.1   |

#### Tailscale (§4.4)

| ID         | Priority | Analysis                                                                                                                              | Sprint |
| ---------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| **FR-040** | **P0**   | **Highest lab priority** after version. Endpoint paths must be confirmed on live Swagger (Tailscale package API under VPN namespace). | 1      |
| **FR-041** | **P0**   | Summary check: advertised routes must include `172.16.0.0/16`. Fail smoke test if missing.                                            | 1      |
| **FR-042** | **P1**   | "Accept subnet routes" — site-to-site requirement per TIPSNTRICKS.                                                                    | 1      |

#### Diagnostics (§4.5)

| ID         | Priority              | Analysis               | Sprint |
| ---------- | --------------------- | ---------------------- | ------ |
| **FR-050** | ~~P1~~ **DEFER v1.1** | Logs — large payloads. | v1.1   |
| **FR-051** | ~~P1~~ **DEFER v1.1** | Services read.         | v1.1   |

#### Writes (§4.6)

| ID         | Priority              | Analysis                                                                           | Sprint |
| ---------- | --------------------- | ---------------------------------------------------------------------------------- | ------ |
| **FR-060** | ~~P1~~ **CUT v1**     | Generic dry_run PATCH removed — unsafe to maintain.                                | —      |
| **FR-061** | ~~P1~~ **DEFER v1.1** | Apply firewall — first write tool when v1 stable.                                  | v1.1   |
| **FR-062** | **P2**                | v1.1 — PATCH singular rule enable/disable; placement risk → require dry_run first. | v1.1   |

#### Out of scope (§4.7)

| IDs        | Action                                                                                |
| ---------- | ------------------------------------------------------------------------------------- |
| FR-900–907 | **No implementation.** Document in README "Out of scope" mirroring REQUIREMENTS §4.7. |

### 2.3 Technical requirements

| ID         | Priority              | Analysis                                                                                                                                        | Sprint |
| ---------- | --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| **TR-001** | **P0**                | FastMCP + official `mcp` SDK — copy `server.py` pattern from proxmox-ve-mcp.                                                                    | 0      |
| **TR-002** | **P0**                | `run_stdio_async()` — same entrypoint contract.                                                                                                 | 0      |
| **TR-003** | **P0**                | `httpx.AsyncClient`; 30s default, 120s for apply ops.                                                                                           | 0      |
| **TR-004** | **P0**                | Header `X-API-Key: {PFSENSE_API_KEY}` — simpler than PVE token format.                                                                          | 0      |
| **TR-005** | **P0**                | `PFSENSE_HOST` (IPv4/IPv6 literal only), `PFSENSE_PORT` default 443. Validate with `ipaddress.ip_address()` in `PfsSettings`; reject DNS names. | 0      |
| **TR-006** | **P1**                | `PFSENSE_VERIFY_SSL` default `true`; document `false` for self-signed lab certs.                                                                | 0      |
| **TR-007** | **P0**                | `API_PREFIX = "/api/v2"` in constants.                                                                                                          | 0      |
| **TR-008** | **P0**                | pfREST envelope differs from PVE: `{code, status, response_id, message, data}`. Map non-200 `code` or HTTP errors → `PfsApiError`.              | 0      |
| **TR-009** | **P0**                | All tools prefixed `pfs_`.                                                                                                                      | 1+     |
| **TR-010** | **P0**                | Pydantic v2 models in `tools/schemas.py`; shared pagination input.                                                                              | 0–1    |
| **TR-011** | **P1**                | `limit`/`offset` on firewall tool only for v1.                                                                                                  | B      |
| **TR-012** | **P2**                | Optional `QueryFilter` helper for `__contains`, `__exact` — v1.1 unless needed for FR-030.                                                      | v1.1   |
| **TR-013** | **P0**                | Never log `PFSENSE_API_KEY`; redact in debug.                                                                                                   | 0      |
| **TR-014** | **P1**                | `load_dotenv()` in `main()` — same as PVE.                                                                                                      | 0      |
| **TR-015** | ~~P1~~ **DEFER**      | Semaphore — add only if concurrent latency observed.                                                                                            | v1.1   |
| **TR-016** | **P0**                | `docs/PFSENSE_API_KEY_SETUP.md` — blocks production use.                                                                                        | C      |
| **TR-017** | **P1**                | pytest + respx: 3 test files, not full matrix.                                                                                                  | C      |
| **TR-018** | **P0**                | Poetry package + scripts `pfsense-mcp`, `pfsense-mcp-smoke`, `pfsense-mcp-bootstrap`, `pfsense-mcp-firewall`.                                   | 0      |
| **TR-019** | **P1**                | `PFS_TESTED_MAJOR_VERSION` constant; README tested matrix.                                                                                      | 4      |
| **TR-020** | **P0**                | Root path dep; `deploy/mcp.sh` auto-discovers.                                                                                                  | C      |
| **TR-021** | ~~P1~~ **DEFER v1.1** | Control params on writes.                                                                                                                       | v1.1   |

### 2.4 Non-functional requirements

| ID          | Priority                     | Analysis                                                                    | Sprint |
| ----------- | ---------------------------- | --------------------------------------------------------------------------- | ------ |
| **NFR-001** | **P0**                       | Enforced via setup doc + smoke test that fails on 403 with privilege hints. | 4      |
| **NFR-002** | ~~P0 for v1~~ **DEFER v1.1** | No write tools → confirm gate unused until v1.1.                            | v1.1   |
| **NFR-006** | **P1**                       | Stdlib logging for v1 (not JSON structured).                                | A      |
| **NFR-007** | ~~P1~~ **SIMPLIFY**          | pfrest/TIPSNTRICKS links in docstrings only.                                | B      |
| **NFR-003** | **P0**                       | 403 → `PfsApiError`; partial data in summary.                               | B      |
| **NFR-004** | **P0**                       | Read-only v1 — GET only.                                                    | B      |
| **NFR-005** | **P1**                       | `asyncio.gather(..., return_exceptions=True)` in summary only.              | B      |
| **NFR-008** | **P1**                       | Root pre-commit when touching Python.                                       | C      |
| **NFR-009** | **P0**                       | Smoke CLI + MCP tool (single QA path).                                      | C      |
| **NFR-010** | **P0**                       | README + `.env.example` + `mcp.json.example`.                               | C      |
| **NFR-011** | **P0**                       | No auth retries.                                                            | A      |
| **NFR-012** | ~~P1~~ **DEFER v1.1**        | Redaction when config reads added.                                          | v1.1   |

### 2.5 Priority summary (after simplicity review)

```text
v1 P0 — ship read-only MCP
  Tools:       6 read (see §1.1)
  Modules:     3 tool files + client + server
  Tests:       config, client, smoke
  Docs:        README, PFSENSE_API_KEY_SETUP.md

DEFER v1.1 — add only when v1 is stable
  Writes, NAT, logs, services, aliases, compliance test, JSON logging, semaphore
```

---

## 3. Architecture

### 3.1 Package layout (simplified)

Copy **patterns** from `proxmox-ve-mcp`, not its directory tree. Target **~15 source files** for v1.

```text
mcp/pfsense-mcp/
├── pyproject.toml
├── README.md                   # includes smoke test matrix (no separate SMOKE_TESTS.md v1)
├── .env.example
├── mcp.json.example
├── docs/
│   ├── REQUIREMENTS.md
│   ├── IMPLEMENTATION.md
│   └── PFSENSE_API_KEY_SETUP.md
├── src/pfsense_mcp/
│   ├── __init__.py
│   ├── server.py
│   ├── smoke_cli.py
│   ├── config.py
│   ├── constants.py            # API_PREFIX, EP_* paths, LAB_LAN_CIDR, LAB_PFSENSE_LAN_IP
│   ├── context.py
│   ├── client/
│   │   ├── __init__.py
│   │   ├── http.py
│   │   └── errors.py           # includes 403 hint text (no permissions.py)
│   └── tools/
│       ├── register.py
│       ├── registry.py
│       ├── schemas.py
│       ├── response.py
│       ├── helpers.py          # require_confirm (v1.1), parse_model
│       ├── system.py           # version, summary, tailscale
│       ├── network.py          # interfaces, firewall rules
│       └── smoke_test.py
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_client.py
    └── test_smoke_test.py
```

**Removed vs v0.1 layout:** `logging_config.py` (stdlib logging), `meta.py`, `interfaces.py`, `routing.py`, `firewall.py`, `tailscale.py`, `diagnostics.py`, `writes.py`, `client/permissions.py`, `tests/tools/*`, `test_requirements_compliance.py`, `docs/SMOKE_TESTS.md`.

### 3.2 Request flow

```text
Cursor Agent
    │ stdio MCP
    ▼
server.py (FastMCP "pfsense")
    │ register_tools
    ▼
tools/<domain>.py impl
    │ @read_tool_handler / @write_tool_handler
    ▼
PfsClient (client/http.py)
    │ HTTPS + X-API-Key
    ▼
https://{PFSENSE_HOST}/api/v2/...
    │
    ▼
JSON envelope → ok_response / error_response
```

### 3.3 pfREST vs PVE — client adaptations

| Aspect           | Proxmox VE MCP                 | pfSense MCP                                      |
| ---------------- | ------------------------------ | ------------------------------------------------ |
| Auth header      | `Authorization: PVEAPIToken=…` | `X-API-Key: …`                                   |
| Base URL         | `https://host:8006/api2/json`  | `https://host:443/api/v2`                        |
| Success envelope | `{data: …}`                    | `{code: 200, status: "ok", data: …}`             |
| Write body       | form-encoded                   | `application/json`                               |
| Apply semantics  | immediate for most POST        | often needs `apply: true` or separate apply call |
| Control params   | N/A                            | `dry_run`, `apply`, `async` in JSON body         |

Implement `_parse_envelope()` in `PfsClient._request()`:

```python
# Pseudocode — implement in client/http.py
if http_status >= 400:
    raise PfsApiError.from_http(status, body)
if body.get("code") != 200:
    raise PfsApiError.from_pfrest(body)
return body.get("data", body)
```

### 3.4 Tool response contract

Identical to proxmox-ve-mcp for agent consistency:

```json
{
  "ok": true,
  "data": {},
  "warnings": ["LAN CIDR check: expected 172.16.0.0/16"],
  "meta": {
    "tool": "pfs_system_summary",
    "tool_class": "read",
    "duration_ms": 842,
    "runbook_ref": "docs/TIPSNTRICKS.md#step-9-tailscale"
  }
}
```

---

## 4. Python environment setup

Base on [`mcp/proxmox-ve-mcp/pyproject.toml`](../proxmox-ve-mcp/pyproject.toml).

### 4.1 Package `pyproject.toml` (target)

```toml
[project]
name = "pfsense-mcp"
version = "0.1.0a1"
description = "Model Context Protocol server for pfSense REST API (pfREST) operations."
readme = "README.md"
authors = [{ name = "Elmorralito", email = "drestrepohinc@gmail.com" }]
requires-python = ">=3.11,<4"
dependencies = [
    "httpx (>=0.28.1,<0.29.0)",
    "mcp (>=1.9.0,<2.0.0)",
    "pydantic (>=2.3.0,<3.0)",
    "pydantic-settings (>=2.6.0,<3.0)",
    "python-dotenv (>=1.0.1,<2.0)",
]

[project.optional-dependencies]
dev = [
    "respx (>=0.22.0,<0.23.0)",
]

[project.scripts]
pfsense-mcp = "pfsense_mcp.server:main"
pfsense-mcp-smoke = "pfsense_mcp.smoke_cli:main"

[project.urls]
HomePage = "https://github.com/Elmorralito/papita-proxmox-lab/tree/main/mcp/pfsense-mcp"
Documentation = "https://github.com/Elmorralito/papita-proxmox-lab/blob/main/mcp/pfsense-mcp/README.md"

[tool.poetry]
package-mode = true
packages = [{ include = "pfsense_mcp", from = "src" }]

[build-system]
requires = ["poetry-core>=2.0.0,<3.0.0"]
build-backend = "poetry.core.masonry.api"
```

### 4.2 Root workspace integration

Add to repo root [`pyproject.toml`](../../pyproject.toml):

```toml
[tool.poetry.dependencies]
pfsense-mcp = { path = "./mcp/pfsense-mcp", develop = true }
```

Install flow (unchanged):

```bash
./deploy/mcp.sh install
./deploy/mcp.sh cursor-sync
```

### 4.3 Environment variables

| Variable              | Required | Default            | Maps to                                            |
| --------------------- | -------- | ------------------ | -------------------------------------------------- |
| `PFSENSE_HOST`        | Yes      | —                  | `PfsSettings.host` — **IPv4 or IPv6 address only** |
| `PFSENSE_PORT`        | No       | `443`              | HTTPS port                                         |
| `PFSENSE_API_KEY`     | Yes      | —                  | `X-API-Key` header                                 |
| `PFSENSE_API_USER`    | No       | `mcp-cursor-agent` | Local pfSense user that owns the API key           |
| `PFSENSE_VERIFY_SSL`  | No       | `true`             | TLS verification                                   |
| `PFSENSE_INTEGRATION` | No       | —                  | Enable live-firewall pytest                        |

#### `PFSENSE_HOST` — IP-only policy (enforced)

Connection target must be a **numeric IP literal**. Hostnames, FQDNs, MagicDNS names (e.g. `*.ts.net`), and bare device labels are **rejected** at startup.

| Allowed                                                       | Rejected                               |
| ------------------------------------------------------------- | -------------------------------------- |
| `172.16.0.1` (lab LAN gateway)                                | `pfsense-fw001`                        |
| `100.64.x.x` (Tailscale address of pfSense, if used directly) | `pfsense-fw001.tailf1ad0d.ts.net`      |
| `2001:db8::1` (IPv6)                                          | `pfsense.local`, `pfsense.example.com` |

**Rationale:** Avoid DNS/Tailscale MagicDNS drift, split-horizon resolution, and ambiguous host identity in automation. Remote workstations reach pfSense via **subnet route** to the LAN IP (`172.16.0.1`), not via tailnet hostname.

**Implementation (`config.py`):** validate in a Pydantic `@field_validator("host")`:

```python
import ipaddress

@field_validator("host")
@classmethod
def validate_host_is_ip(cls, value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("PFSENSE_HOST must not be empty")
    if "://" in cleaned:
        raise ValueError("PFSENSE_HOST must not include a URL scheme")
    try:
        ipaddress.ip_address(cleaned)
    except ValueError as exc:
        raise ValueError(
            "PFSENSE_HOST must be an IPv4 or IPv6 address literal; "
            "hostnames and FQDNs are not allowed"
        ) from exc
    return cleaned
```

Unit tests must cover: valid IPv4/IPv6, rejection of FQDN, rejection of bare hostname, rejection of empty/scheme-prefixed values.

### 4.4 Cursor `mcp.json.example`

```json
{
  "mcpServers": {
    "pfsense": {
      "command": "poetry",
      "args": ["run", "pfsense-mcp"],
      "cwd": "/absolute/path/to/papita-proxmox-lab",
      "env": {
        "PFSENSE_HOST": "172.16.0.1",
        "PFSENSE_PORT": "443",
        "PFSENSE_API_KEY": "REPLACE_FROM_SECRET_STORE",
        "PFSENSE_API_USER": "mcp-cursor-agent",
        "PFSENSE_VERIFY_SSL": "true"
      }
    }
  }
}
```

**Notes:**

- `cwd` must be repo root (not `mcp/pfsense-mcp`) so Poetry resolves the workspace venv.
- **`PFSENSE_HOST` must be an IP address** — use `172.16.0.1` (lab LAN gateway) when on-segment or when reaching pfSense over an approved Tailscale subnet route to `172.16.0.0/16`. Do not use MagicDNS or local domain names.

---

## 5. Phase plan (simplified)

Replaces the five-sprint plan (v0.1). Phases **A → B → C** only.

### Phase A — Foundation (~1 day)

**Goal:** Server starts; client parses one pfREST response.

| Task                                                  | Files                     |
| ----------------------------------------------------- | ------------------------- |
| Package skeleton + pyproject                          | root                      |
| `PfsSettings` (IP-only host)                          | `config.py`               |
| Endpoint constants (from live Swagger — **B-1**)      | `constants.py`            |
| `PfsClient` + `PfsApiError`                           | `client/`                 |
| Context + stdlib logging in `server.py`               | `context.py`, `server.py` |
| Tool scaffold (registry, response, helpers, register) | `tools/`                  |
| Stub tool `pfs_get_version`                           | `system.py`               |

**Exit:** `poetry run pfsense-mcp` starts; `test_config.py` + `test_client.py` pass.

---

### Phase B — Read v1 (~2–3 days)

**Goal:** Lab verify via MCP — Tailscale route + LAN + firewall snapshot.

| Task                                      | Tool                       |
| ----------------------------------------- | -------------------------- |
| Version                                   | `pfs_get_version`          |
| Interfaces + LAN CIDR warning             | `pfs_list_interfaces`      |
| Tailscale advertised routes               | `pfs_get_tailscale_status` |
| Aggregated check (gateways/routes inline) | `pfs_system_summary`       |
| Firewall rules (`limit` default 50)       | `pfs_list_firewall_rules`  |

**Exit:** Agent answers "Is `172.16.0.0/16` advertised?" — matches `tailscale-pfsense-lan.sh verify` intent.

**Summary implementation — keep thin:**

```python
# tools/system.py — max 4 parallel GETs
results = await asyncio.gather(
    client.get(EP_VERSION),
    client.get(EP_INTERFACES),
    client.get(EP_TAILSCALE),
    client.get(EP_GATEWAYS),
    return_exceptions=True,
)
```

Do not add more sub-calls until v1.1.

---

### Phase C — Ship (~1–2 days)

**Goal:** Installable, documented, smoke-tested.

| Task                                            | Deliverable                              |
| ----------------------------------------------- | ---------------------------------------- |
| Smoke MCP tool + CLI (same checks)              | `smoke_test.py`, `smoke_cli.py`          |
| API key setup guide                             | `PFSENSE_API_KEY_SETUP.md`               |
| README (disclaimer, smoke matrix, out-of-scope) | `README.md`                              |
| Cursor + env examples                           | `mcp.json.example`, `.env.example`       |
| Root path dependency                            | `pyproject.toml`                         |
| `mcp/README.md` row                             | deploy discovery                         |
| Optional live test                              | `PFSENSE_INTEGRATION=1` single test file |

**Smoke matrix (9 checks — only QA surface):**

| #   | Check                                            | Core         |
| --- | ------------------------------------------------ | ------------ |
| 1   | Config / IP-only host valid                      | yes          |
| 2   | API reachable                                    | yes          |
| 3   | API key not 401                                  | yes          |
| 4   | REST API settings reachable (inline, not a tool) | yes          |
| 5   | LAN CIDR on interface                            | yes          |
| 6   | Tailscale advertises `172.16.0.0/16`             | **optional** |
| 7   | `tailscale_firewall_policy`                      | yes          |
| 8   | `restapi_access_policy`                          | yes          |
| 9   | `api_endpoints_policy`                           | yes          |

Exit code uses **core** (`core_passed` — all except #6). Policy details: [POLICY.md](./POLICY.md).

**Exit:** `./deploy/mcp.sh install && ./deploy/mcp.sh smoke --server pfsense-mcp`; Cursor green.

---

### v1.1 backlog (do not start until v1 shipped)

| Item                                                        | Notes                                       |
| ----------------------------------------------------------- | ------------------------------------------- |
| `pfs_apply_firewall_changes`                                | First write; `confirm=true` + audit logging |
| `pfs_list_nat_rules`, `pfs_query_logs`, `pfs_list_services` | Extended reads                              |
| `test_requirements_compliance.py`                           | When tool count > 10                        |
| `logging_config.py` JSON stderr                             | When writes exist                           |
| Semaphore / concurrency limit                               | If measured need                            |
| `docs/SMOKE_TESTS.md`                                       | Split from README when matrix grows         |
| FR-062 rule toggle                                          | Specific tool, not generic PATCH            |

---

## 5.1 Deprecated — five-sprint plan (v0.1)

<details>
<summary>Collapsed reference — superseded by Phases A–C above</summary>

Sprints 0–4 and 13+2 tool catalog replaced by §1.1 and §5. See git history for full v0.1 sprint tables.

</details>

---

## 6. Endpoint discovery (minimal)

**Before Phase B:** confirm paths on live pfSense Swagger; add to `constants.py` only.

```python
EP_SYSTEM_VERSION = "/system/version"
EP_RESTAPI_SETTINGS = "/system/restapi/settings"
EP_INTERFACES = "/interfaces"
EP_GATEWAYS = "/routing/gateways"      # confirm on instance
EP_FIREWALL_RULES = "/firewall/rules"
EP_TAILSCALE = "/vpn/tailscale/settings"  # confirm on instance — B-1
```

Do **not** commit OpenAPI exports or codegen tools for v1.

---

## 7. Testing strategy (minimal)

| Layer                             | Scope                                  | v1?      |
| --------------------------------- | -------------------------------------- | -------- |
| `test_config.py`                  | IP-only host, env validation           | Yes      |
| `test_client.py`                  | Envelope parse, 403/401 errors (respx) | Yes      |
| `test_smoke_test.py`              | Smoke logic mocked                     | Yes      |
| `PFSENSE_INTEGRATION=1`           | One optional live test                 | Optional |
| Per-tool test files               | Each `*_impl`                          | **v1.1** |
| `test_requirements_compliance.py` | Full traceability                      | **v1.1** |

**Fixture pattern (respx):**

```python
@pytest.fixture
def pfrest_ok(respx_mock):
    respx_mock.get("https://pfsense.test/api/v2/system/version").respond(
        json={"code": 200, "status": "ok", "data": {"version": "26.03", "product": "pfSense"}}
    )
```

---

## 8. Risk register

| Risk                                          | Impact                 | Mitigation                                                       |
| --------------------------------------------- | ---------------------- | ---------------------------------------------------------------- |
| Unofficial package removed on pfSense upgrade | MCP breaks             | Document reinstall in README; smoke test detects missing package |
| Endpoint path differs from public Swagger     | Wrong URLs             | Instance Swagger export; constants indirection                   |
| Per-endpoint privilege gaps                   | 403 on tools           | `pfs_check_api_key` + setup doc with privilege matrix            |
| Firewall rule writes block traffic            | Outage                 | v1 read-only default; writes require confirm + dry_run doc       |
| Login protection lockout                      | API blocked            | No auth retries (NFR-011); dedicated API key user                |
| Large rule/log payloads                       | Agent context overflow | Default pagination limits; summary tools over raw dumps          |
| Tailscale endpoint namespace unknown          | Sprint 1 blocked       | Sprint 0 pre-flight Swagger capture                              |

---

## 9. Phase traceability (simplified)

| Phase | Primary requirements                                                                    |
| ----- | --------------------------------------------------------------------------------------- |
| **A** | TR-001–008, TR-013–018, BR-002, BR-004, BR-010, NFR-011                                 |
| **B** | BR-001, BR-003, BR-008, FR-001, FR-004, FR-010, FR-022, FR-030, FR-040–042, NFR-003–005 |
| **C** | BR-007, BR-009, BR-011, TR-016–017, TR-019–020, NFR-001, NFR-009–010                    |

---

## 10. Definition of done (v1 — read-only)

- [ ] **7 read tools** registered; **0 write tools**
- [ ] `./deploy/mcp.sh install && ./deploy/mcp.sh smoke --server pfsense-mcp` passes
- [ ] Cursor MCP server `pfsense` green after `cursor-sync`
- [ ] `docs/PFSENSE_API_KEY_SETUP.md` complete
- [ ] README lists out-of-scope items (writes, Tailscale Admin API)
- [ ] `test_config.py` + `test_client.py` + `test_smoke_test.py` pass
- [ ] ~15 source files under `src/pfsense_mcp/` (avoid scope creep)

---

## 11. Immediate next actions

1. **B-1 pre-flight:** Live Swagger → 6 endpoint constants in `constants.py`
2. **Phase A:** Scaffold per §3.1 simplified layout
3. **Phase B:** Implement 6 tools only
4. **Phase C:** Docs + smoke + root pyproject path dep
5. Validate against `./deploy/tailscale-pfsense-lan.sh verify`

---

_Implementation strategy v0.2 — simplicity review 2026-06-10. v0.1 five-sprint plan superseded._
