"""Post-change verification: fresh management connection, nft presence, LAN-vantage TCP check."""

import ipaddress
from typing import Any

from openwrt_mcp.config import OpenwrtSettings
from openwrt_mcp.errors import DomainError
from openwrt_mcp.policy.templates import section_name
from openwrt_mcp.router.agent_client import AgentClient
from openwrt_mcp.router.transport import run_subprocess, ssh_base_argv


async def lan_vantage_probe(settings: OpenwrtSettings, port: int) -> str:
    """TCP-connect from the LAN vantage host to the router.

    Returns ``open``, ``refused`` (both prove the path is not filtered), ``filtered`` (timeout) or ``skipped``.
    """
    if not settings.probe_host:
        return "skipped"
    ipaddress.ip_address(settings.lan_host)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("invalid port")
    key = settings.probe_key_path or settings.ssh_key_path
    known_hosts = settings.probe_known_hosts_path or settings.known_hosts_path
    argv = ssh_base_argv(
        key_path=key,
        known_hosts_path=known_hosts,
        user=settings.probe_user,
        host=settings.probe_host,
        port=22,
        connect_timeout=10,
    )
    remote = f"timeout 5 bash -c 'exec 3<>/dev/tcp/{settings.lan_host}/{port}'"
    try:
        rc, _ = await run_subprocess([*argv, remote], None, 20.0)
    except DomainError:
        return "filtered"
    return {0: "open", 1: "refused", 124: "filtered"}.get(rc, "filtered")


async def run_probes(
    settings: OpenwrtSettings,
    agent: AgentClient,
    plan: dict[str, Any],
    *,
    expect_revision: str | None,
) -> dict[str, Any]:
    """Collect verification evidence for ``plan`` and return ``{"passed": bool, "checks": {...}}``."""
    checks: dict[str, Any] = {}
    try:
        snap = await agent.inspect()  # always a fresh SSH connection (ControlMaster disabled)
        checks["new_mgmt_connection"] = "ok"
    except DomainError:
        return {"passed": False, "checks": {"new_mgmt_connection": "fail"}}

    checks["fw4_loaded"] = "ok" if snap.get("nft_loaded") else "fail"
    checks["uci_committed"] = (
        "ok" if (expect_revision is None or snap.get("config_revision") == expect_revision) else "fail"
    )
    checks["no_wan_exposure"] = "ok" if not snap.get("wan_exposure") else "fail"
    checks["tailscale_running"] = "ok" if snap.get("tailscale_running") else "fail"

    present = set(snap.get("nft_rules", []))
    rule_checks = []
    for op in plan["operations"]:
        sect = section_name(op["rule_id"])
        if op["type"] == "firewall.rule.upsert":
            rule_checks.append(sect in present)
        else:
            rule_checks.append(sect not in present)
    checks["rule_state"] = "ok" if all(rule_checks) else "fail"

    mgmt = await lan_vantage_probe(settings, 22)
    checks["lan_vantage_mgmt"] = "skipped" if mgmt == "skipped" else ("ok" if mgmt in ("open", "refused") else "fail")
    for op in plan["operations"]:
        if op["type"] == "firewall.rule.upsert":
            res = await lan_vantage_probe(settings, op["fields"]["dest_port"])
            checks["synthetic_allow"] = (
                "skipped" if res == "skipped" else ("pass" if res in ("open", "refused") else "fail")
            )
    passed = all(v in ("ok", "pass", "skipped") for v in checks.values())
    return {"passed": passed, "checks": checks}
