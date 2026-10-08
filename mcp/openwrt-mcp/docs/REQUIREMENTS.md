# OpenWrt MCP Server: Requirements and Traceability

**Package:** `mcp/openwrt-mcp` v0.1.0a1 | **Date:** 2026-10-07
**Sources:** session PDFs (design baseline), `docs/DISCOVERY.md` (live image facts), `docs/THREAT_MODEL.md`.
**Scope:** firewall domain, rollout stages 0-4. Software, plugins, features, services are deferred.

Legend: **Met** | **Partial** | **Deferred**

## Refinements to the source documents

1. FHIR, HIPAA, GDPR, SOC 2 and "MCPx" content is dropped (not applicable / undefined).
2. Approval separation in a local stdio setup is enforced by a signature the agent cannot produce (passphrase on `/dev/tty`).
3. `owrt_plan_confirm` re-verifies server side; it is not a model claim.
4. Synthetic probes use nft ruleset presence + LAN-vantage TCP classification (no router listener available).
5. The template is constrained: `src=lan` only, `proto=tcp`, ACCEPT hardcoded, `src_ip` inside `172.16.0.0/16`, reserved ports denied.
6. Tool names use the repo's prefix convention (`owrt_*`).
7. Verify deadline (120 s, cap 300 s) and overall transaction deadline are separate policy values.

## Functional requirements

| ID     | Requirement                                                                  | Status   | Evidence                                    |
| ------ | ---------------------------------------------------------------------------- | -------- | ------------------------------------------- |
| FR-001 | Inspect firewall state (revision, agent-owned rules, runtime summary)        | Met      | `owrt_firewall_inspect`                     |
| FR-002 | Smoke test config, host-key pin, auth, agent, revision                       | Met      | `owrt_run_smoke_tests`, `openwrt-mcp-smoke` |
| FR-010 | Plan one template (`allow_tcp_from_lan`) upsert/delete for agent-owned rules | Met      | `owrt_firewall_plan_rule`                   |
| FR-011 | Immutable plan: digest, state precondition, policy revision, expiry, diff    | Met      | `policy/engine.py`, `store/`                |
| FR-012 | Idempotent planning by `idempotency_key`                                     | Met      | `store.create_plan`                         |
| FR-020 | Out-of-band exact-plan human approval producing a one-time signed grant      | Met      | `openwrt-mcp-approve`                       |
| FR-030 | Apply with watchdog armed first, persistent journal and backup               | Met      | `owrt_firewall_apply_plan`, router agent    |
| FR-031 | Confirm only after server-side verification passes                           | Met      | `owrt_plan_confirm`                         |
| FR-032 | Manual rollback and automatic rollback on missed deadline/reboot             | Met      | `owrt_plan_rollback`, watchdog              |
| FR-040 | Stable error codes without secrets/tracebacks                                | Met      | `errors.py`                                 |
| FR-050 | Hash-chained local audit that never blocks recovery                          | Met      | `store/audit.py`                            |
| FR-900 | Software, plugin, feature, service tools; OIDC; broker; SIEM                 | Deferred | See THREAT_MODEL                            |

## Non-functional / security requirements

| ID      | Requirement                                                      | Status                                                                  |
| ------- | ---------------------------------------------------------------- | ----------------------------------------------------------------------- |
| NFR-001 | Deny by default; unknown tool args and fields rejected           | Met (`tests/test_tools_schema.py`)                                      |
| NFR-002 | Router agent re-authorizes independently of the MCP service      | Met (agent allowlist)                                                   |
| NFR-003 | Restricted SSH key, pinned host key, bounded JSON on stdin       | Met (`router/transport.py`, installer)                                  |
| NFR-004 | Prohibited operations stay denied even with approval             | Met (`policy/templates.py`)                                             |
| NFR-005 | Live fault tests (killed agent, reload hang, reboot unconfirmed) | Partial: scripts provided, require on-site run (see `docs/GO_NO_GO.md`) |

## Tool catalog

| Tool                       | Class                                |
| -------------------------- | ------------------------------------ |
| `owrt_firewall_inspect`    | read                                 |
| `owrt_run_smoke_tests`     | read                                 |
| `owrt_firewall_plan_rule`  | write (plans only; no router change) |
| `owrt_plan_status`         | read                                 |
| `owrt_firewall_apply_plan` | write                                |
| `owrt_plan_confirm`        | write                                |
| `owrt_plan_rollback`       | destructive                          |

## Error codes

`APPROVAL_REQUIRED`, `APPROVAL_EXPIRED`, `STATE_PRECONDITION_FAILED`, `TARGET_NOT_AUTHORIZED`, `OPERATION_PROHIBITED`,
`TARGET_LOCKED`, `VERIFICATION_FAILED` (from the PDF) plus `INVALID_INPUT`, `NOT_FOUND`, `ROUTER_ERROR`, `INTERNAL`.
