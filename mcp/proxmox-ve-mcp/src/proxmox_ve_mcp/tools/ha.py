"""HA manager MCP tool implementations (read-only)."""

import re
import time
from typing import Any

from proxmox_ve_mcp.constants import HA_DEFAULT_SHUTDOWN_POLICY, HA_REQUIRED_SHUTDOWN_POLICY
from proxmox_ve_mcp.context import get_client
from proxmox_ve_mcp.tools.helpers import normalize_list
from proxmox_ve_mcp.tools.response import ok_response, tool_handler

_LRM_MODES = ("wait_for_agent_lock", "maintenance", "active", "idle", "lost_agent_lock", "old timestamp")
_POLICY_RE = re.compile(r"(?:^|,)\s*shutdown_policy=([a-z_]+)")


def parse_shutdown_policy(options: Any) -> str:
    """Return ``ha.shutdown_policy`` from ``/cluster/options`` (dict or property string)."""
    ha = options.get("ha") if isinstance(options, dict) else None
    if isinstance(ha, dict) and ha.get("shutdown_policy"):
        return str(ha["shutdown_policy"])
    if isinstance(ha, str):
        match = _POLICY_RE.search(ha)
        if match:
            return match.group(1)
    return HA_DEFAULT_SHUTDOWN_POLICY


def _lrm_mode(status: str) -> str:
    lowered = status.lower()
    return next((mode for mode in _LRM_MODES if mode in lowered), "unknown")


async def _optional_get(client: Any, path: str, warnings: list[str]) -> Any:
    try:
        return await client.get(path)
    except Exception as exc:
        warnings.append(f"Could not load {path}: {exc}")
        return None


@tool_handler("pve_get_ha_status")
async def pve_get_ha_status_impl() -> str:
    """HA manager, per-node LRM state, managed resources, rules/groups, and shutdown policy."""
    started = time.perf_counter()
    client = get_client()
    warnings: list[str] = []

    current = normalize_list(await client.get("/cluster/ha/status/current"))
    resources = normalize_list(await _optional_get(client, "/cluster/ha/resources", warnings))
    options = await _optional_get(client, "/cluster/options", warnings)

    rules_warnings: list[str] = []
    rules = await _optional_get(client, "/cluster/ha/rules", rules_warnings)
    rules_source = "rules"
    if rules is None:
        rules = await _optional_get(client, "/cluster/ha/groups", rules_warnings)
        rules_source = "groups"
    if rules is None:
        warnings.extend(rules_warnings)
        rules_source = "unavailable"

    manager = next((e for e in current if e.get("type") == "master"), None)
    quorum = next((e for e in current if e.get("type") == "quorum"), None)
    lrms = [
        {"node": e.get("node"), "mode": _lrm_mode(str(e.get("status", ""))), "status": e.get("status")}
        for e in current
        if e.get("type") == "lrm"
    ]
    services = [
        {k: e.get(k) for k in ("sid", "node", "state", "crm_state", "request_state", "status") if k in e}
        for e in current
        if e.get("type") == "service"
    ]
    active_lrm_nodes = [lrm["node"] for lrm in lrms if lrm["mode"] == "active"]

    policy = parse_shutdown_policy(options) if options is not None else None
    policy_ok = policy == HA_REQUIRED_SHUTDOWN_POLICY
    if policy is not None and not policy_ok:
        warnings.append(
            f"ha.shutdown_policy is {policy!r}; power tools require {HA_REQUIRED_SHUTDOWN_POLICY!r} "
            "(apply via papita-cluster-quorum-ha.sh / HA_SHUTDOWN_POLICY)."
        )
    if active_lrm_nodes:
        warnings.append(
            "LRM active on " + ", ".join(str(n) for n in active_lrm_nodes) + ": these nodes run HA resources and "
            "self-fence (watchdog) if they lose quorum."
        )
    if manager is None:
        warnings.append("No HA manager (master) entry; HA stack may be idle or not configured.")

    data = {
        "shutdown_policy": policy,
        "shutdown_policy_ok": policy_ok,
        "quorum": {"quorate": bool(int(quorum.get("quorate", 0))), "status": quorum.get("status")} if quorum else None,
        "manager": {"node": manager.get("node"), "status": manager.get("status")} if manager else None,
        "lrms": lrms,
        "active_lrm_nodes": active_lrm_nodes,
        "resources": resources,
        "resource_count": len(resources),
        "services": services,
        "rules_source": rules_source,
        "rules": normalize_list(rules) if rules is not None else [],
    }
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_get_ha_status", data, duration_ms=duration_ms, warnings=warnings)
