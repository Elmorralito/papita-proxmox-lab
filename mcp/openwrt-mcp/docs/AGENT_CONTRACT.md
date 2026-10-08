# Router agent contract (protocol v1)

Transport: SSH, restricted key, pinned host key, forced command
`/usr/libexec/openwrt-mcp-agent`. One JSON object on stdin (max 65536 bytes), one JSON object on stdout.
Nothing is interpolated into a shell. Unknown fields are rejected.

## Envelope

Request: `{"v":1,"op":"<name>", ...}`

Success: `{"ok":true,"v":1, ...}`

Failure: `{"ok":false,"v":1,"error":{"code":"<CODE>","message":"<text>"}}`

Error codes: `BAD_REQUEST`, `OPERATION_PROHIBITED`, `APPROVAL_INVALID`, `APPROVAL_EXPIRED`,
`STATE_PRECONDITION_FAILED`, `TARGET_LOCKED`, `WATCHDOG_UNAVAILABLE`, `VALIDATION_FAILED`,
`APPLY_FAILED`, `NOT_FOUND`, `CLOCK_UNSYNCED`, `NEEDS_MANUAL`.

## Operations

| op         | request fields                                                                                                                                          | response fields                                                                                                                                                                            |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `inspect`  | none                                                                                                                                                    | `agent_version`, `config_revision`, `agent_owned_rules[]`, `pending_changes`, `nft_loaded`, `nft_rules[]`, `wan_exposure`, `watchdog_alive`, `active_txn`, `tailscale_running`, `clock_ok` |
| `validate` | `operations[]`, `state_precondition`                                                                                                                    | `valid`, `candidate_ok`                                                                                                                                                                    |
| `apply`    | `plan_id`, `plan_digest`, `state_precondition`, `operations[]`, `recovery{mode,deadline_s}`, `grant{payload,signature}`, `router_id`, `policy_revision` | `state`, `journal_id`, `backup`, `new_revision`, `verify_deadline_s`                                                                                                                       |
| `confirm`  | `plan_id`                                                                                                                                               | `state` = `confirmed`                                                                                                                                                                      |
| `rollback` | `plan_id`                                                                                                                                               | `state` = `rolled_back`                                                                                                                                                                    |
| `status`   | optional `plan_id`                                                                                                                                      | `state`, journal summary                                                                                                                                                                   |

## Operations list (`operations[]`)

```json
{"type":"firewall.rule.upsert","rule_id":"allow-metrics",
 "fields":{"template":"allow_tcp_from_lan","src":"lan","proto":"tcp","dest_port":9100,"family":"ipv4","src_ip":"172.16.0.0/24"}}
{"type":"firewall.rule.delete","rule_id":"allow-metrics"}
```

- `rule_id`: `^[a-z0-9][a-z0-9-]{0,31}$`. UCI section is `mcp_<rule_id>` with `_` replacing `-`; only sections with
  the `mcp_` prefix and `option owned_by 'openwrt-mcp'` can be changed or deleted.
- `fields`: `src` must be `lan`; `proto` must be `tcp`; `dest_port` 1-65535 (not 22, 80, 443, 41641); `family`
  in `ipv4|ipv6|any` (default `ipv4`); `src_ip` optional, an IPv4 CIDR contained in `172.16.0.0/16`.
- The agent re-validates all of the above independently of the MCP service.

## Digest

`plan_digest = "sha256:" + sha256(canonical_json({router_id, operations, state_precondition, policy_revision, recovery}))`

Canonical JSON: keys sorted, separators `,` and `:`, no whitespace, integers/booleans/strings only. Strings are restricted
to `[A-Za-z0-9_./:@-]` so escaping rules cannot diverge between Python and ucode. The agent recomputes the digest and rejects
mismatches (`APPROVAL_INVALID`).

## Grant

`grant.payload` is canonical JSON: `{v, plan_id, plan_digest, state_precondition, router_id, policy_revision,
requester, approver, expires_at (epoch int), nonce}`. `grant.signature` is the base64 content of a `usign` signature
file. The agent verifies with `usign -V -m payload -p /etc/openwrt-mcp/approver.pub -x sig`, checks every bound
field against the request, checks expiry against the router clock, and records the nonce persistently (one-time use).

## Transaction state machine (router journal)

`armed -> applied_unconfirmed -> confirmed | rolled_back | needs_manual`

Journal and backup live in `/etc/openwrt-mcp/journal/` (persistent). A watchdog heartbeat lives in
`/var/run/openwrt-mcp/watchdog.alive` (volatile). The watchdog:

- rolls back an `applied_unconfirmed` journal whose `/proc/uptime` deadline has passed;
- rolls back (or marks `needs_manual` on drift) any unconfirmed journal whose `boot_id` differs from the current boot;
- never depends on SSH, the MCP service or the workstation.
