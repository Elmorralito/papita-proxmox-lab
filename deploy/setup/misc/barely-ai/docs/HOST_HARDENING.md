# Host hardening (S6)

- `unattended-upgrades` daily security updates (`/etc/apt/apt.conf.d/20auto-upgrades`)
- SSH: key-only, `AllowUsers root`, no X11 (`/etc/ssh/sshd_config.d/99-papita-hardening.conf`)
- `fail2ban` jail `sshd` only (LAN `172.16.0.0/16` ignored); no inference-port jails
