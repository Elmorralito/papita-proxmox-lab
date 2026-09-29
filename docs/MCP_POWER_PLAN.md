# MCP full-lab power control — strategy and plan

Implementation plan for the backlog in [TODO.md](./TODO.md), checked against [ARCHITECTURE.md](./ARCHITECTURE.md). Goal: shut the lab down and bring it back from Cursor MCP without SSH, reproducing the 2026-09-25 shutdown safely.

## Decisions

| Topic                      | Decision                                                                                                                                                                                                                                        |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TrueNAS reachability       | The LAN router guest (pfSense VM 100 today) is the **only** path to TrueNAS. NAS calls must happen while the router guest runs.                                                                                                                 |
| LAN router                 | pfSense will be replaced by **OpenWrt**. Nothing may hard-code "pfSense" or VMID 100; use `PVE_LAB_INFRA_VMIDS` (default `100`). The router guest stays on `local-lvm` on the entry node (never on NFS / HA: circular dependency with the NAS). |
| HA during shutdown         | `ha.shutdown_policy=freeze` is **required**. Set by `papita-cluster-quorum-ha.sh` (`HA_SHUTDOWN_POLICY`); PVE power tools refuse to run if it is not `freeze`.                                                                                  |
| Ceph                       | Not used. `pve_set_ceph_noout` is dropped (Won't); no FR-903 exception; no `PveClient.put()` needed for now.                                                                                                                                    |
| Cold start                 | QDevice host `172.16.0.99` (always on) sends WoL to TrueNAS, then `pve-001`, then the peers.                                                                                                                                                    |
| Cross-server orchestration | Agent-driven runbook (skills + TIPSNTRICKS). `pve_shutdown_cluster` returns `next_steps` naming the TrueNAS call; MCP servers never call each other.                                                                                            |

## Shutdown sequence

1. **Preflight (PVE):** `pve_cluster_health` → `quorate=true`, QDevice voting, `entry_node` resolved (`local=1` in `/cluster/status`); `pve_get_ha_status` → `shutdown_policy=freeze`; `pve_list_guests` → note NFS-backed guests.
2. **Preflight (TrueNAS):** `truenas_system_summary`, `truenas_list_nfs_clients`, no running scrub/replication job.
3. **Peers:** `stopall` each non-entry node, wait for `stopped` / `exitstatus=OK`.
4. **Entry node:** shut down each guest except `PVE_LAB_INFRA_VMIDS` (router stays up).
5. **Peers:** node shutdown while still quorate → `pve_wait_nodes_state(offline)`. Entry node + QDevice = 2/5 votes → not quorate (expected; only node-local ops follow).
6. **TrueNAS:** `truenas_shutdown(delay_s≈300, expected_clients=["172.16.0.101"])` — must run while the router guest is up.
7. **Entry node:** `pve_shutdown_node(<entry>, allow_entry_host=true)`; router guest stops with it; API loss = success with warning.

Tune `delay_s` from measured entry-node shutdown time: if the entry node is still up when the NAS goes away, its `hard` NFS mounts stall until the systemd umount timeout (~90 s).

## Startup sequence

1. **Cold start:** `./deploy/proxmox.sh wake-lab --ip-address 172.16.0.99` → SSH to QDevice host → WoL TrueNAS, wait for NFS (`:2049`), then WoL `pve-001` and the peers (`pve-001` alone has no quorum, so its guests wait for the peers).
2. **Automatic:** `post-startup-proc` on `pve-001` waits for quorum and wakes peers.
3. **MCP:** `pve_wait_nodes_state(online)` → `pve_wake_on_lan(nodes=all_offline)` for stragglers → `pve_cluster_health` quorate.
4. **MCP (after router guest is up):** `truenas_run_smoke_tests`, `truenas_list_nfs_clients` shows all four nodes.

## Caveats, challenges, workarounds

| Caveat                     | Challenge                                                                           | Workaround                                                                                                                                    | Residual risk                                                                           |
| -------------------------- | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| Router guest on entry node | NAS unreachable once the router stops                                               | Delayed NAS shutdown (step 6) before entry node (step 7)                                                                                      | Entry node slower than `delay_s` → umount stall                                         |
| Entry host loss            | PVE MCP talks to one host by DNS name                                               | Resolve entry via `/cluster/status` `local=1`; always last; `allow_entry_host`; connection loss after last shutdown = success                 | —                                                                                       |
| Quorum / HA                | 4 PVE + QDevice = 5 votes, quorum 3; `/etc/pve` read-only on the last node          | All cluster-config writes while quorate; `freeze` policy gate; refuse if QDevice not voting                                                   | Verify guest stop + node shutdown work non-quorate on PVE 9                             |
| NFS `hard` mounts          | Running NFS guests freeze if NAS disappears; NFSv4 stale leases                     | Stop guests first; `expected_clients` gate; `force=true` override                                                                             | Stale client entries for ~90 s lease                                                    |
| Cold start via QDevice     | Reaching `.99` when the router is down (Tailscale egress may go through the router) | Give `.99` egress independent of the router, or run `wake-lab` from a LAN workstation; `wakeonlan` installed by `qdevice-server-bootstrap.sh` | Physical power-on as last resort                                                        |
| Long MCP calls             | Full shutdown exceeds tool-call timeout                                             | `wait_for_completion=false` + `pve_wait_for_task` / `pve_wait_nodes_state` (≤120 s per call)                                                  | —                                                                                       |
| Privileges                 | New `Sys.PowerMgmt`, `Sys.Audit`; TrueNAS key role for `system.shutdown`            | Dedicated `PapitaPower` role; update `PVE_TOKEN_SETUP.md`, `API_KEY_SETUP.md`, `pve_check_token` hints                                        | —                                                                                       |
| Config drift               | Stale `TRUENAS_HOST`, lab pool/export constants                                     | Phase 0 fixes + grep for old names                                                                                                            | —                                                                                       |
| Safety                     | Destructive tools auto-approved                                                     | `destructive` class, `confirm=true` + `reason`, `plan_only=true` dry run; keep off auto-run allowlists                                        | —                                                                                       |
| OpenWrt migration          | Router-specific assumptions                                                         | Router-agnostic config; migration checklist covers Tailscale subnet route `172.16.0.0/16`, NAS DMZ rules, NAS Tailscale egress                | If OpenWrt gives the NAS an independent path, drop the delay and shut the NAS down last |

## Phases

### Phase 0 — unblock

- [x] Fix `TRUENAS_HOST` in `$CURSOR_HOME/mcp.json` → `truenas-ha-scale.tailf1ad0d.ts.net` (+ `TRUENAS_LAB_NFS_EXPORT`); reload server.
- [x] Lab constants: `main_data_storage` / `/mnt/main_data_storage` (constants, README, SMOKE_TESTS, skill, tests).
- [x] TrueNAS error mapping: connect inside `try`; `DNS_ERROR`, `CONNECTION_REFUSED`, `CONNECT_TIMEOUT`, `TLS_ERROR`, `HANDSHAKE_ERROR` with hints; smoke check `host_reachable` first.
- [x] PVE error mapping: no empty messages; distinct codes for DNS / timeout / refused / TLS.
- [x] `pve_cluster_health`: true `quorate` from `/cluster/status`, `entry_node`, QDevice status.
- [ ] Done when `truenas_run_smoke_tests` passes and `pve_cluster_health` reports `quorate` (needs the lab powered on).

### Phase 1 — read-only prerequisites

- [x] `pve_get_ha_status` (manager, LRMs, resources, rules, `shutdown_policy`).
- [x] `truenas_list_nfs_clients` (map IPs to nodes via `TRUENAS_LAB_PVE_NODES`; stale NFSv4 leases flagged).
- [x] `pve_wait_for_task` / `pve_wait_nodes_state` (≤120 s per call; API loss = terminal `offline`).
- [x] `wait_for_task(timeout_sec=…)` plumbing; `wait_for_job` filtered by id.
- [x] `HA_SHUTDOWN_POLICY=freeze` in `default.truenas.nfs.env` + applied by `papita-cluster-quorum-ha.sh`.
- [ ] Live: run `./deploy/proxmox.sh setup-cluster-ha` (applies freeze), then `pve_get_ha_status`, `truenas_list_nfs_clients`, `pve_run_smoke_tests(extended=true)`.

### Phase 2 — single-target writes

- [x] `pve_shutdown_node` (entry-node guard, quorum-impact warning, freeze gate, `plan_only`).
- [x] `pve_stop_guest`.
- [x] `pve_wake_on_lan` (+ missing-MAC hint).
- [x] `truenas_shutdown` / `truenas_reboot` (NFS-client + running-job guards, `expected_clients`, `delay_s`, `reason`, `plan_only`; socket drop = ok).
- [x] `deploy/proxmox.sh wake-lab` (QDevice-host WoL; MACs in `deploy/setup/misc/cluster/default.wol.macs`; `wakeonlan` added to `qdevice-server-bootstrap.sh`).
- [x] REQUIREMENTS: reverse TrueNAS FR-902, correct PVE FR-904 / OQ-2.
- [x] Privileges: `MCPAgentPower` (`Sys.PowerMgmt`) in `PVE_TOKEN_SETUP.md`; TrueNAS key role in `API_KEY_SETUP.md`; smoke `node_power_permissions`.
- [ ] Live: fill real MACs in `default.wol.macs`; grant power roles; staged validation (hard-stop disposable guest → reboot `pve-004` → peer shutdown + `pve_wake_on_lan` → `truenas_reboot` with PVE off).

### Phase 3 — orchestration

- [x] `pve_shutdown_cluster` (`keep_running_vmids` from `PVE_LAB_INFRA_VMIDS`, `plan_only`, `continue_on_error`, `next_steps`); resumable stage machine, ≤120 s per call, in-flight tasks reused on re-call.
- [x] Runbook in both skill copies (`.cursor/skills/*-mcp/` and `~/.cursor/skills/*-mcp/`) and TIPSNTRICKS ("Full-lab shutdown / startup via MCP").
- [ ] Done when the 2026-09-25 shutdown is reproduced from Cursor with no SSH.

### Phase 4 — backlog

Medium/Low items from TODO.md (migrate, snapshots, backups, firewall read, TrueNAS services/snapshots/scrub/SMART/replication/updates/network, apps, UPS, subscription, runbook resources).

### Separate track — pfSense → OpenWrt

Checklist to draft: router guest on `local-lvm`, WAN/LAN bridges (`vmbr1` / `vmbr0`), Tailscale subnet router, NAS DMZ rules, NAS Tailscale egress, update `PVE_LAB_INFRA_VMIDS`, retire `pfsense-mcp`.

## Per-tool checklist

Every tool: `register.py` / `registry.py`, `schemas.py`, `REQUIREMENTS.md`, `UTILITY_API_CALLS.md`, `SMOKE_TESTS.md` case, both skill copies, token/API key privilege doc.

## Validation

1. Unit tests with mocked clients: entry-node resolution, quorum impact, orchestrator order (`plan_only`), error mapping, connection-drop-as-success.
2. Read-only smoke: true quorum, HA status, NFS clients, `plan_only` runs.
3. Staged live: hard-stop disposable guest → reboot `pve-004` → peer shutdown + `pve_wake_on_lan` → `truenas_reboot` with PVE off → one full supervised cycle.
