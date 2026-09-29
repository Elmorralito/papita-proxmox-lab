# TODO — MCP tool gaps

Pending tools and fixes for `mcp/proxmox-ve-mcp` and `mcp/truenas-mcp`. Found during the full lab shutdown on 2026-09-25: the cluster had to be stopped with `./deploy/proxmox.sh stop-cluster` over SSH, and the NAS could not be shut down at all (no MCP tool, SSH disabled, stale Tailscale host).

Strategy, ordering, and phases: [MCP_POWER_PLAN.md](./MCP_POWER_PLAN.md).

Conventions for every new tool:

- Envelope `{ok, data, warnings, meta}`, registered in `tools/register.py` / `tools/registry.py`, schema in `tools/schemas.py`.
- Write tools require `confirm=true` and are classed `write` or `destructive` in `meta.tool_class`.
- Long operations accept `wait_for_completion=true` (PVE: reuse `client/tasks.py` `wait_for_task`; TrueNAS: `client/jobs.py` `wait_for_job`).
- Add a row to the package `REQUIREMENTS.md`, `docs/UTILITY_API_CALLS.md`, and a smoke case in `docs/SMOKE_TESTS.md` where it can run read-only.
- Update the skill tables in `~/.cursor/skills/proxmox-ve-mcp/SKILL.md` and `~/.cursor/skills/truenas-mcp/SKILL.md`.

---

## Config

### [x] Fix stale `TRUENAS_HOST` (live smoke pending — lab powered off)

- **Problem:** `$CURSOR_HOME/mcp.json` has `TRUENAS_HOST=truenas-scale-oldtimers.tailf1ad0d.ts.net`. That name no longer resolves; the NAS now appears in Tailscale as `truenas-ha-scale` (`100.126.197.118`). Every TrueNAS MCP call fails with `[Errno -2] Name or service not known`.
- **Fix:** set `TRUENAS_HOST=truenas-ha-scale.tailf1ad0d.ts.net`, reload the `truenas` server in Cursor Settings → MCP, run `truenas_check_api_key`.
- **Also:** update any repo defaults/examples that reference the old name (`mcp/truenas-mcp/mcp.json.example`, `deploy/setup/misc/cluster/default.truenas.nfs.env` if it uses the DNS name, TIPSNTRICKS).
- **Done when:** `truenas_run_smoke_tests` passes from Cursor.

---

## proxmox-ve-mcp

### High — full shutdown/startup via MCP

#### [x] `pve_shutdown_node`

- **Why:** node power-off is the one step of `stop-cluster` MCP cannot do today. Already listed in the v2 backlog (§7.3) as `destructive`.
- **API:** `POST /nodes/{node}/status` with `command=shutdown` or `command=reboot`. Plain REST — the backlog note implying SSH is unnecessary.
- **Inputs:** `node` (validated `^[a-zA-Z0-9._-]+$`), `command: shutdown|reboot`, `confirm`.
- **Safety:**
  - Refuse if `node` is the API entry host (`api_entry_host` from `pve_cluster_health`) while other nodes are still online, unless `allow_entry_host=true` — otherwise the MCP loses its connection mid-sequence.
  - Warn if running guests remain on the node (list via `pve_list_guests`), since shutdown will force the node's own stop sequence.
  - Warn when shutting down this node drops the online count below quorum.
- **Token privilege:** `Sys.PowerMgmt` on `/nodes/{node}` (not in current roles — update `PVE_TOKEN_SETUP.md`).
- **Files:** `tools/nodes.py`, `schemas.py`.
- **Done when:** a single node can be rebooted from Cursor and comes back in `pve_list_nodes`.

#### [x] `pve_shutdown_cluster`

- **Why:** an agent composing node shutdowns by hand can easily power off the entry node first and strand the rest. One tool should encode the order used by `deploy/proxmox.sh stop_cluster`.
- **Sequence:**
  1. For each peer (non-entry) node: `POST /nodes/{node}/stopall`, wait for the task, then `POST /nodes/{node}/status command=shutdown`.
  2. Entry node: shut down guests except `PVE_LAB_INFRA_VMIDS` (LAN router guest), then shutdown only if `include_entry_node=true` (mirrors `-sln`) — after the delayed TrueNAS shutdown (see plan).
- **Inputs:** `confirm`, `include_entry_node` (default `false`), `keep_running_vmids`, `guest_timeout_s` (passed to `stopall`), `wait_for_completion`, `plan_only`.
- **Output:** per-node result list (`stopall` UPID, shutdown UPID, errors) so partial failures are visible.
- **Safety:** abort before any node shutdown if a `stopall` task fails and `continue_on_error=false`; check HA status first (see `pve_get_ha_status`) and refuse unless `ha.shutdown_policy=freeze`.
- **Token privilege:** `VM.PowerMgmt` + `Sys.PowerMgmt` on `/`.
- **Done when:** the 2026-09-25 shutdown can be reproduced from Cursor with one call.

#### [x] `pve_wake_on_lan`

- **Why:** the startup counterpart; today only `./deploy/proxmox.sh start-cluster`.
- **API:** `POST /nodes/{node}/wakeonlan` — sent from an online node to wake `{node}` using the MAC configured in the node config (`pvenode config set -wakeonlan <MAC>`).
- **Fix docs:** `REQUIREMENTS.md` FR-904 says "No REST", which is wrong. Move WoL from Won't to Should, and drop it from OQ-2's "stay Bash-only" note.
- **Inputs:** `node` (target to wake), optional `via_node` (defaults to the API entry host), `confirm`.
- **Extras:** `nodes=all_offline` shortcut to wake every offline member, matching `start-cluster`; return a hint when the target has no WoL MAC configured.
- **Token privilege:** `Sys.PowerMgmt` on `/nodes/{via_node}`.
- **Done when:** a powered-off node comes back online via the tool and shows up in `pve_cluster_health`.

#### [x] `pve_stop_guest`

- **Why:** FR-022 (v2). `pve_shutdown_guest` is ACPI/graceful; a hung guest blocks `stopall` until timeout and leaves no MCP way to finish the job.
- **API:** `POST /nodes/{node}/{qemu|lxc}/{vmid}/status/stop`.
- **Inputs:** `node`, `vmid`, `guest_type`, `confirm`, `wait_for_completion`, optional `overrule_shutdown=true` (qemu: abort an in-progress shutdown task).
- **Safety:** class as `destructive` (equivalent to pulling power); warn in the envelope that unsaved guest state is lost.
- **Token privilege:** `VM.PowerMgmt` (already in the power role).
- **Files:** `tools/guests.py`, alongside `pve_shutdown_guest_impl`.

#### [-] `pve_set_ceph_noout` — Won't (Ceph is not used in this lab)

- **Why:** planned shutdowns should set `noout` so Ceph does not start rebalancing when OSDs disappear; today that happens only in `deploy/setup/pre-shutdown-proc.sh` on the node. `pve_stopall_guests` explicitly does not set it.
- **API:** `PUT /cluster/ceph/flags/noout` with `value=1|0`; read current flags with `GET /cluster/ceph/flags`.
- **Scope:** `noout` only (optionally `norebalance`). Keep OSD start/stop/destroy and disk wipe out of scope — this is a narrow exception to FR-903, record it there.
- **Inputs:** `enabled: bool`, `confirm`.
- **Safety:** return current `HEALTH_*` status in `data`; if Ceph is not installed (HTTP 500, missing `ceph-mon`), return a clear "Ceph not installed" error instead of a token error.
- **Token privilege:** `Sys.Modify` on `/`.
- **Files:** `tools/ceph.py`.

#### [x] `pve_get_ha_status`

- **Why:** there is no way to see HA state via MCP (`pve_list_resources` does not accept `haresource`). HA can restart guests on surviving nodes during a staged shutdown, and its state matters before migrations.
- **API:** `GET /cluster/ha/status/current` (manager + LRM per node), `GET /cluster/ha/resources` (managed guests and requested state), `GET /cluster/ha/rules` on PVE 9 (node-affinity rules created by `setup-cluster-ha`).
- **Output:** manager status, per-node LRM state (`active`/`idle`/`wait_for_agent_lock`), managed resources with `state` and current node.
- **Token privilege:** `Sys.Audit` on `/`.
- **Files:** new section in `tools/cluster.py`.

### Medium

#### [ ] `pve_migrate_guest`

- **Why:** FR-023 (v2 backlog). Needed for rolling maintenance: drain a node, then reboot it.
- **API:** `POST /nodes/{node}/qemu/{vmid}/migrate` (`target`, `online=1` for live) and `POST /nodes/{node}/lxc/{vmid}/migrate` (`restart=1`, containers cannot live-migrate).
- **Inputs:** `node`, `vmid`, `guest_type`, `target`, `online` (qemu), `confirm`, `wait_for_completion`.
- **Safety:** pre-check with `GET /nodes/{node}/qemu/{vmid}/migrate` (reports local disks/blocking resources); refuse if the target is offline.
- **Token privilege:** `VM.Migrate` on `/vms/{vmid}`.

#### [ ] `pve_list_snapshots` / `pve_create_snapshot`

- **Why:** create is in the v2 backlog for backup workflows; listing is needed to make it useful and to check before risky changes.
- **API:** `GET|POST /nodes/{node}/{qemu|lxc}/{vmid}/snapshot` (`snapname`, `description`, `vmstate` for qemu RAM).
- **Inputs (create):** `node`, `vmid`, `guest_type`, `snapname` (validated), `description`, `include_ram` (qemu), `confirm`.
- **Out of scope:** rollback and delete (destructive) — keep for a later RFC.
- **Token privilege:** `VM.Audit` (list), `VM.Snapshot` (create).

#### [ ] `pve_list_backups` / `pve_run_backup`

- **Why:** check that backups exist before shutdowns/upgrades, and trigger an ad-hoc one.
- **API:** list with `GET /nodes/{node}/storage/{storage}/content?content=backup`; scheduled jobs with `GET /cluster/backup`; run with `POST /nodes/{node}/vzdump` (`vmid`, `storage`, `mode=snapshot|suspend|stop`, `compress=zstd`).
- **Inputs (run):** `node`, `vmid` (or list), `storage`, `mode` (default `snapshot`), `confirm`, `wait_for_completion`.
- **Safety:** refuse `mode=stop` unless explicitly set; warn when the target storage is low on space (`pve_list_storage`).
- **Token privilege:** `VM.Backup` + `Datastore.AllocateSpace` on the target storage; `Datastore.Audit` to list.

#### [ ] `pve_get_firewall_rules`

- **Why:** v2 backlog; lets agents verify the cluster firewall set up in `setup-pve-node.sh` step 14 without SSH.
- **API:** `GET /cluster/firewall/options`, `/cluster/firewall/rules`, `/cluster/firewall/groups`, `/cluster/firewall/ipset`, and per node `GET /nodes/{node}/firewall/rules`.
- **Output:** enabled flag, default policies, rules (action, source, dest, port, comment) — read-only.
- **Token privilege:** `Sys.Audit`.

#### [x] `pve_wait_for_task` / `pve_wait_nodes_state`

- **Why:** after the 2026-09-25 shutdown, "are the nodes actually off?" had to be answered with SSH timeouts. Agents also need to wait on UPIDs returned by other tools without re-implementing polling.
- **`pve_wait_for_task`:** expose the existing `client/tasks.py` `wait_for_task` — inputs `upid`, `timeout_s`; returns final `status`/`exitstatus` and the last log lines (`pve_get_task_log`).
- **`pve_wait_nodes_state`:** poll `GET /cluster/status` until the listed nodes reach `online` or `offline`, or timeout; returns per-node final state and elapsed time. When waiting for full cluster offline, the API endpoint itself disappears — treat connection loss after the last node shutdown as success with a warning.
- **Token privilege:** `Sys.Audit`.

### Improvements to existing tools

#### [x] `pve_cluster_health`: true quorum

- **Why:** quorum is currently approximated from online counts, which is why the skill says "use SSH `pvecm status`".
- **Change:** read the `type=cluster` entry of `GET /cluster/status` — it carries `quorate`, `nodes`, and `version`. Return `quorate: bool` alongside the existing counts and drop the "approximate" caveat from the tool docstring, the skill, and REQUIREMENTS FR-006.
- **Bonus:** include the QDevice vote when present (from the same payload or `GET /cluster/config/qdevice` on PVE 8+).

### Low

#### [ ] `pve_ssh_exec_read`

- **Why:** v2 backlog; the only way to cover data with no REST endpoint: `sensors -j` (`get-temp`), `pvecm status`, `ceph -s` detail, `journalctl` excerpts.
- **Design:** strict allowlist of commands (no free-form shell), SSH key from env (`PAPITA_SSH_IDENTITY_FILE`), output size cap, read-only class. Reuse the `deploy/proxmox.sh` SSH options.
- **Risk:** adds SSH credentials to the MCP process — keep behind an opt-in env flag.

#### [ ] Subscription status (FR-013)

- **API:** `GET /nodes/{node}/subscription` → `status`, `level`, `nextduedate`.
- **Why:** surface "no subscription" as a warning in `pve_run_smoke_tests` instead of silence; low value in the lab.

#### [ ] MCP resource `runbook://tipsntricks/{section}`

- **Why:** OQ-4; lets agents fetch the relevant TIPSNTRICKS section instead of reading the whole doc. `RUNBOOK_REFS` in the package already maps tools to sections — serve those sections as MCP resources.

---

## truenas-mcp

### High

#### [x] `truenas_shutdown` / `truenas_reboot`

- **Why:** the NAS could not be powered off on 2026-09-25 through any automated path. Reverses FR-902 (currently Won't) — record the decision and new guardrails in `REQUIREMENTS.md`.
- **API:** `system.shutdown` / `system.reboot` (SCALE 24.10+ take a `reason` string and optional `{"delay": seconds}`). Both return a job — poll with `wait_for_job` only until the socket drops.
- **Inputs:** `confirm`, `reason` (required, logged on the NAS), `delay_s` (default 0), `force` (default `false`).
- **Safety:**
  - Refuse unless `force=true` when `truenas_list_nfs_clients` reports connected clients — the PVE cluster mounts `truenas-nfs-main`, `truenas-nfs-logs`, `truenas-nfs-media`, and guests on NFS disks hang if the NAS disappears first.
  - Refuse if a scrub or replication job is running (`core.get_jobs` / `pool.scrub` state) unless `force=true`.
  - Class `destructive`; envelope warning that the MCP connection will drop.
- **Files:** `tools/writes.py` (or new `tools/power.py`), `schemas.py`.
- **Done when:** after `pve_shutdown_cluster`, the NAS can be shut down from Cursor and the pre-check passes with zero NFS clients.

#### [x] `truenas_list_nfs_clients`

- **Why:** the safety gate for NAS shutdown, and an easy way to confirm which PVE nodes actually have the HA export mounted.
- **API:** `nfs.get_nfs3_clients` and `nfs.get_nfs4_clients` (SCALE 24.04+).
- **Output:** per client: IP/hostname, NFS version, export path; map IPs to PVE node names when they match the cluster ring addresses (optional, via `TRUENAS_LAB_*` config).
- **Files:** `tools/sharing.py`.

#### [x] Clear connection errors

- **Problem:** a DNS failure surfaced as `INTERNAL_ERROR: [Errno -2] Name or service not known`, which reads like a server bug rather than bad config.
- **Change:** in `client/websocket.py`, map `socket.gaierror` → `CONNECTION_ERROR` with message naming `TRUENAS_HOST` and a hint ("host does not resolve — check the Tailscale device name or use the LAN IP"). Map connection refused / TLS errors / auth rejection to distinct codes too.
- **Apply to:** `truenas_check_api_key`, `truenas_run_smoke_tests` (first check should be "resolve + TCP connect to :443"), and `smoke_cli.py`.
- **Done when:** pointing `TRUENAS_HOST` at a nonexistent name gives a one-line actionable error.

### Medium

#### [ ] `truenas_list_services` / `truenas_set_service`

- **Why:** see whether NFS/SSH/SMART services are running, and toggle SSH on for a temporary CLI fallback (it was disabled on 2026-09-25).
- **API:** `service.query` (state + `enable` on boot); `service.start` / `service.stop` (jobs); `service.update` for boot-enable.
- **Inputs (set):** `service` (allowlist: `ssh`, `nfs`, `smartd`, `ups`), `action: start|stop`, `enable_on_boot` (optional), `confirm`.
- **Safety:** refuse `nfs` stop while NFS clients are connected unless `force=true`.

#### [ ] `truenas_list_snapshots` / `truenas_create_snapshot`

- **Why:** snapshot before risky changes (e.g. before PVE upgrades that touch NFS storage); snapshot tasks are already on the backlog.
- **API:** `zfs.snapshot.query` (filter by dataset), `zfs.snapshot.create` (`dataset`, `name`, `recursive`), `pool.snapshottask.query` for scheduled tasks.
- **Inputs (create):** `dataset`, `name` (validated), `recursive`, `confirm`.
- **Out of scope:** snapshot delete/rollback.

#### [ ] `truenas_run_scrub`

- **Why:** trigger a scrub after unclean shutdowns or disk alerts instead of waiting for the schedule (`truenas_list_scrub_tasks` is read-only).
- **API:** `pool.scrub.run` (`pool_name`, `threshold=0` to force) — returns a job.
- **Safety:** refuse if a scrub is already running on the pool; warn that it adds I/O load to the PVE NFS export.

#### [ ] `truenas_run_smart_test`

- **Why:** run a SHORT/LONG test on a suspect disk, complementing `truenas_list_smart_results`.
- **API:** `smart.test.manual_test` with `[{"identifier": <disk>, "type": "SHORT|LONG"}]`.
- **Inputs:** `disks` (names from `truenas_list_disks`), `type` (default `SHORT`), `confirm`.

#### [ ] `truenas_list_replication_tasks`

- **Why:** confirm off-box copies exist and are healthy before shutdowns/upgrades.
- **API:** `replication.query`, `cloudsync.query` — last run state, schedule, target.
- **Class:** read-only.

#### [ ] `truenas_check_updates`

- **Why:** know whether a SCALE update is pending (and whether it may change `TRUENAS_WS_PATH`) before planning maintenance.
- **API:** `update.check_available` (+ `update.get_trains` for current train).
- **Class:** read-only; never applies updates.

#### [ ] `truenas_get_network_summary`

- **Why:** see interfaces, IPs, and default route without the WebUI — would have helped diagnose the host rename.
- **API:** `interface.query`, `network.general.summary` (IPs, nameservers, default routes), `network.configuration.config` (hostname).
- **Class:** read-only. NIC/IP changes stay out of scope (skill caveat).

### Low

#### [ ] App stop/start

- **Why:** restart Scrutiny (or other apps) when it stalls; `truenas_list_apps` is read-only today.
- **API:** `app.stop` / `app.start` / `app.redeploy` (jobs). Catalog install/upgrade stays out of scope (FR-900).
- **Inputs:** `app_name` (allowlist from `TRUENAS_LAB_SCRUTINY_APP_NAME` or explicit list), `action`, `confirm`.

#### [ ] UPS config read

- **Why:** if a UPS is attached, its shutdown mode/timer determines whether the NAS powers off before or after the PVE cluster during an outage.
- **API:** `ups.config`, `service.query` for `ups`.
- **Class:** read-only.
