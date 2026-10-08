# openwrt-mcp — Go / No-Go checklist

Live writes on the router (`openwrt-pi`) require an explicit operator decision. **Status of every item below is
recorded honestly; unchecked means not yet validated on real hardware.**

## A. Validated in CI / OpenWrt 25.12.5 rootfs container (done)

- [x] Unit tests (policy, digest, grants, tool schemas, plan flow) — `pytest` in `mcp/openwrt-mcp`
- [x] Agent container tests (`OPENWRT_MCP_DOCKER_TESTS=1`): apply/confirm/rollback, unconfirmed → watchdog rollback
      without MCP/SSH, confirm after deadline, simulated reboot while unconfirmed, killed agent mid-apply
      (→ `needs_manual`), watchdog unavailable (apply refused), reload failure → rollback, **reload hang
      (60 s timeout) → rollback**, replayed/tampered/forged/other-plan grants, state drift, pending UCI changes,
      prohibited ports/fields, foreign-section protection.
- [x] Cross-language canonical digest and usign-compatible signature verification (Python ↔ ucode / `usign`)

## B. Preconditions before any live write (operator)

- [ ] Physical/console access to the Pi (or another out-of-band path) is available during the test window
- [ ] Router config backed up manually (`sysupgrade -b`) and stored off-router
- [ ] Agent installed with `papita-openwrt-mcp-agent-install.sh install` (restricted key, pinned host key)
- [ ] `owrt_run_smoke_tests` passes (read-only), including fresh SSH inspect and forced-command check
- [ ] Approver key generated (`openwrt-mcp-approve keygen`) and public key installed on the router
- [ ] Explicit go-ahead recorded (who/when): \***\*\*\*\*\***\_\_\***\*\*\*\*\***

## C. On-Pi fault tests (run in this order, one at a time, with fallback access)

Use a throw-away canary rule `mcp_allow_metrics` (tcp/9100, LAN src inside 172.16.0.0/16).

1. [ ] **Happy path**: plan → approve → apply → verify probes → confirm. Rule visible in `nft list ruleset`.
2. [ ] **Unconfirmed**: apply, do not confirm. Watchdog rolls back at the deadline; Tailscale and SSH stay up.
3. [ ] **MCP gone**: apply, kill the MCP server/SSH session. Rollback still happens on the router.
4. [ ] **Killed agent**: `kill -9` the agent during apply → journal armed, state `needs_manual`; resolve per
       RUNBOOK, then `--clear`.
5. [ ] **Reboot while unconfirmed**: `reboot` after apply; boot reconcile rolls back (`last.json` = rolled_back).
6. [ ] **Watchdog unavailable**: stop `openwrt-mcp-watchdog`; apply must be refused.
7. [ ] **Reload hang** (optional, only with fallback access): emulate with a wrapper as in the container test.
8. [ ] **Rollback of a confirmed rule** via `owrt_plan_rollback` returns config to the pre-state hash.

## D. Negative matrix on the real router

- [ ] Apply without grant → `APPROVAL_REQUIRED`; expired grant → `APPROVAL_EXPIRED`; replay → rejected
- [ ] Digest changed after approval → rejected; state drift → `STATE_PRECONDITION_FAILED`
- [ ] Ports 22/53/80/443/41641, WAN source, src outside 172.16.0.0/16 → `OPERATION_PROHIBITED` / `TARGET_NOT_AUTHORIZED`
- [ ] Unknown tool argument → rejected by schema

## E. Sign-off

| Item                   | Result                   | Date | By  |
| ---------------------- | ------------------------ | ---- | --- |
| Sections A (automated) | PASS                     |      |     |
| Sections B–D (on-Pi)   | NOT RUN                  |      |     |
| Go for live use        | NO-GO until B–D complete |      |     |

## Deferred (out of v1)

DNS/DHCP, Tailscale, routing/WAN/VPN, SSH/network config changes, package management, multi-router fleet,
HSM-backed approval. `pfsense-mcp` is kept as is (not deprecated); it stays useful alongside `openwrt-mcp`.
