# Stage 0 discovery: `openwrt-pi` (read-only)

Collected 2026-10-07 over SSH with read-only commands only (no writes, no service restarts).
This replaces assumptions in the design PDFs with facts for the actual image.

## Target image

| Item            | Finding                                                                                     |
| --------------- | ------------------------------------------------------------------------------------------- |
| OpenWrt         | 25.12.5 (`r33051-f5dae5ece4`), `bcm27xx/bcm2711`, `aarch64_cortex-a72` (Raspberry Pi)       |
| Package manager | `apk` (not `opkg`)                                                                          |
| firewall4       | `2025.03.17~b6e51575-r2`                                                                    |
| Rootfs          | `/dev/root` 98.3M, 40.7M free (flash-backed; keep journal writes minimal)                   |
| RAM             | ~1.9 GB                                                                                     |
| Tailscale       | running; `openwrt-pi` advertises `172.16.0.0/16` (single point of failure for remote admin) |
| Firewall config | 3 zones, 4 forwardings, 10 rules, **no `include` sections**                                 |

## Capabilities that the design depends on

| Capability                      | Result                                                                           | Decision                                                                                                                                                                                           |
| ------------------------------- | -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `fw4 check`                     | Present; prints `Ruleset passes nftables check.`                                 | Used to validate a candidate before reload. It validates the _rendered_ ruleset from the current UCI view, so validation stages changes (never committed) and reverts. See "Candidate validation". |
| `ucode` + modules               | `fs`, `uci`, `ubus`, `digest`, `uloop`, `log`, `math`                            | Router agent is written in ucode (strict JSON parse, no shell interpolation). `digest` gives sha256. No `socket` module, so no in-agent listener.                                                  |
| `usign`                         | `/usr/bin/usign` present                                                         | Router re-verifies approval grants (ed25519, signify-compatible) against a pinned public key.                                                                                                      |
| Dropbear                        | `v2025.89`; supports `command="..."`, `no-pty`, `no-port-forwarding`, `restrict` | Restricted key with forced command is viable. Verify `restrict` behaviour at install time (the install script greps the binary and refuses if absent).                                             |
| `procd`                         | present                                                                          | Watchdog is a procd-managed, respawned service (not a detached shell).                                                                                                                             |
| `/etc/dropbear/authorized_keys` | exists, mode 600                                                                 | Agent key line is appended; existing admin key is never touched.                                                                                                                                   |

## Decisions resolved from the plan's open items

1. **Grant signing:** ed25519 key held on the workstation, encrypted with a passphrase typed on `/dev/tty` (PKCS#8 `BestAvailableEncryption`). Signature emitted in `usign`/signify format so the router can verify with its own `usign`. Keychain/Touch ID or FIDO2 is a documented upgrade, not required for v0.1.
2. **`fw4 check` on an isolated candidate:** `fw4` reads the live UCI view and has no alternate config dir. Validation therefore stages the change with `uci set` (uncommitted, in the delta store), runs `fw4 check`, then `uci revert firewall`. The agent refuses to do this if `uci changes` is already non-empty (shared pending changes), and holds the write lock for the duration.
3. **Dropbear restrictions:** supported (see table). The install script verifies the options exist in the installed binary before writing the key line.
4. **Probe approach:** no router-side listener is available without extra packages. Verification therefore combines (a) the rule being present in the loaded nft ruleset (`nft list ruleset` filtered), (b) a fresh management SSH connection over Tailscale, (c) a LAN-vantage TCP connect from the PVE main node (open or refused both prove reachability; timeout means filtered), and (d) a router-side "no WAN exposure" assertion. Limitation: with the default `lan` input policy ACCEPT, an additional allow rule is behaviourally redundant, so the canary proves the transaction machinery, not a behavioural change.

## SDK pin

`mcp==1.30.0` installed in the dev environment (FastMCP, stdio). The package declares `mcp>=1.9,<2` like the sibling servers. The 2026-07-28 HTTP transport revision is not used (stdio only).

## Known limits (documented, not solved)

- Agent lock does not stop LuCI or a manual root shell from writing `/etc/config/firewall` mid-transaction. The agent detects drift by revision digest before apply and before rollback, and refuses to overwrite a drifted config on rollback (status `needs_manual`).
- The Pi has no RTC. The agent refuses grants when the router clock looks unsynchronised (epoch before 2025-01-01), and the watchdog uses `/proc/uptime` plus `boot_id` rather than wall-clock.
- True out-of-band recovery for the Pi is a keyboard/HDMI or serial console; it is not provided by this software.
