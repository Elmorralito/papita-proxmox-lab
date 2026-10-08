# Threat model (homelab-scaled)

Design baseline: the two session PDFs ("Policy-Constrained MCP Administration for OpenWrt"). This document records how
each mandatory property is enforced in v0.1 and what is deferred.

## Trust zones

- **Untrusted:** the model, tool arguments, router log text, anything returned by third parties.
- **Trusted control plane:** the `openwrt-mcp` process, its SQLite state and audit file on the workstation, the approval CLI.
- **Router zone:** `openwrt-pi` agent, journal, watchdog.

Deferred from the PDFs (extension points only): OIDC/OAuth for a shared HTTP service, credential broker, plugin runtime,
SIEM export, software/plugin/feature/service tools.

## Mandatory properties and enforcement

| Property                                            | Enforcement                                                                                                                                                                     |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Deny by default                                     | Only registered `owrt_*` tools; one template; allowlisted fields; prohibited-operation list; router agent re-authorizes independently.                                          |
| Typed operations only                               | Pydantic models with `extra="forbid"` on every tool; FastMCP argument models are patched to forbid unknown top-level args. No shell/UCI/ubus passthrough tool exists.           |
| Approval bound to target, op, digest, state, expiry | Ed25519 grant over canonical payload; verified in the MCP service and again by `usign` on the router; one-time nonce recorded on both sides. Approval is never a tool argument. |
| Independent recovery before mutation                | Agent refuses `apply` without a fresh watchdog heartbeat; persistent journal + backup written before any change; procd watchdog rolls back with no MCP/SSH dependency.          |
| Scoped credentials                                  | Dedicated restricted SSH key (forced command, no pty, no forwarding), separate from the root admin key. Bearer/API secrets are never forwarded.                                 |
| Verify real behavior                                | Fresh SSH connection, LAN-vantage TCP check, nft ruleset presence, no-WAN-exposure assertion; `owrt_plan_confirm` re-runs them server side.                                     |

## Principal risks and mitigations

- **Agent self-approval (shared OS user):** the grant needs a passphrase-protected private key read through `/dev/tty`;
  the approve CLI refuses non-TTY stdin. Residual risk: an agent with a keylogger or the passphrase. Mitigation path: Keychain/FIDO2.
- **Prompt injection via router text:** only fixed-schema fields are returned; free text (rule names/comments) is not surfaced
  as instructions and is redacted/truncated.
- **Management lockout (Tailscale subnet router):** WAN/SSH/Tailscale ports and non-`mcp_` sections are prohibited; watchdog + verification include a Tailscale-path SSH check.
- **Drift / concurrent writers:** revision digest precondition before apply; agent rejects pending `uci changes`; rollback refuses to overwrite drifted config.
- **Replay:** one-time nonce, plan expiry, state precondition.
- **Audit tampering/outage:** hash-chained JSONL; audit write failure is logged and never blocks recovery.

## Out of scope

Firmware flashing, unrestricted scripts, package install, SSH/auth/DNS/VPN/network changes, and anything outside `mcp_*` firewall sections.
