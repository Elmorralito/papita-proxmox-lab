# Kernel performance policy — barely-ai-agent

## Decision (2026-11-11)
**Keep** boot flags:

`mitigations=off intel_pstate=active processor.max_cstate=1 idle=nomwait`

### Why allowed
- Host role: single-purpose AI inference (Qwen chat + Kev decisions)
- Not a general workstation; no interactive multi-user desktop workload
- Network: nftables LAN allowlist + Bearer API keys on :8080/:8009
- Services: non-root `llama` / `kev` with systemd sandbox

### Risks accepted
- Speculative-execution side channels easier if an attacker can run code on the box
- Slightly higher exposure if sandbox escape occurs

### Revisit when
- Host runs untrusted containers/CI jobs
- Browsers or third-party desktop apps are used on the machine
- Services are exposed beyond `172.16.0.0/16`

### Change back
Edit `/etc/default/grub.d/99-llama-perf.cfg`, remove `mitigations=off` (and optionally C-state pins), then `update-grub && reboot`.
