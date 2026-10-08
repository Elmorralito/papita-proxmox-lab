# openwrt-mcp — Operator runbook

## Install the router agent

From the workstation (admin key is used only for installation):

```bash
deploy/setup/misc/openwrt/papita-openwrt-mcp-agent-install.sh install \
  --host 100.78.68.87 --admin-key ~/.ssh/id_ed25519_NASGW
deploy/setup/misc/openwrt/papita-openwrt-mcp-agent-install.sh status --host 100.78.68.87 --admin-key ...
```

It installs `/usr/libexec/openwrt-mcp-agent`, the procd watchdog, the approver public key, and a restricted
`authorized_keys` line (`command=...,no-pty,no-port-forwarding,...`). It never touches firewall, network,
Tailscale or sshd configuration. `uninstall` removes all of it.

## Pin the router host key

```bash
mkdir -p ~/.config/openwrt-mcp
ssh-keyscan -t ed25519 100.78.68.87 > ~/.config/openwrt-mcp/known_hosts
# compare with the router: ssh root@100.78.68.87 'dropbearkey -y -f /etc/dropbear/dropbear_ed25519_host_key'
```

## Approver key and approving a plan

```bash
poetry run openwrt-mcp-approve keygen          # passphrase-encrypted key; install .pub on router via installer
poetry run openwrt-mcp-approve list
poetry run openwrt-mcp-approve show <plan_id>
poetry run openwrt-mcp-approve approve <plan_id>   # needs a TTY; type the 12-hex digest prefix
```

Agents cannot approve: the CLI refuses without a TTY and the passphrase is read from `/dev/tty`.

## Key rotation

- **Approver key**: `keygen` a new pair, re-run installer `install --approver-pub new.pub`, delete the old key.
  Outstanding grants become invalid.
- **Agent SSH key**: delete `~/.ssh/id_ed25519_openwrt_mcp*`, re-run installer `install` (replaces the restricted line).

## Manual rollback / recovery

State on router: `/etc/openwrt-mcp/journal/` (`active.json`, `last.json`, `<plan>.firewall.bak`).

1. `owrt_plan_status` (or `ssh` agent `status`) shows `needs_manual` / `pending_confirmation`.
2. Inspect `/etc/config/firewall` against the backup: `diff /etc/openwrt-mcp/journal/<plan>.firewall.bak /etc/config/firewall`.
3. Restore manually if the agent refused (config drifted):
   `cp /etc/openwrt-mcp/journal/<plan>.firewall.bak /etc/config/firewall && /etc/init.d/firewall reload`.
4. Clear the journal: `/usr/libexec/openwrt-mcp-agent --clear` (run locally on the router).
5. Remove stray sections named `mcp_*` with `owned_by 'openwrt-mcp'` only if the backup does not contain them.

## Out-of-band recovery

If LAN or Tailscale access is lost: use the console/physical access, `/etc/init.d/firewall stop` is NOT
recommended; instead restore the backup as above, or `firstboot`-free option: `sysupgrade -r <backup.tar.gz>`.
The watchdog also rolls back unconfirmed changes automatically (default deadline 120 s) even after reboot.

## Watchdog

`/etc/init.d/openwrt-mcp-watchdog status|restart`. Heartbeat: `/var/run/openwrt-mcp/watchdog.alive`.
Apply is refused when the heartbeat is stale.

## Audit

`~/.local/state/openwrt-mcp/audit.jsonl` is hash-chained; verify through the smoke tests
(`openwrt-mcp-smoke`). Audit failures never block recovery.
