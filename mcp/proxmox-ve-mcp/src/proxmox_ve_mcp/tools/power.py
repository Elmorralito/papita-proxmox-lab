"""Node power MCP tools: guarded shutdown/reboot and Wake-on-LAN."""

import time
from typing import Any

from proxmox_ve_mcp.client.errors import PveApiError
from proxmox_ve_mcp.client.tasks import node_states
from proxmox_ve_mcp.constants import API_LOST_ERROR_CODES, HA_REQUIRED_SHUTDOWN_POLICY
from proxmox_ve_mcp.context import get_client, get_settings
from proxmox_ve_mcp.tools.cluster import qdevice_status
from proxmox_ve_mcp.tools.ha import ha_placement, parse_shutdown_policy
from proxmox_ve_mcp.tools.helpers import normalize_list, parse_model, require_confirm
from proxmox_ve_mcp.tools.response import ok_response, write_tool_handler
from proxmox_ve_mcp.tools.schemas import ShutdownNodeInput, WakeOnLanInput

WOL_MAC_HINT = (
    "Configure the target's WoL MAC while it is online: `pvenode config set -wakeonlan <MAC>` "
    "(stored in /etc/pve/nodes/<node>/config); BIOS/NIC WoL must be enabled (setup step 3)."
)


async def _cluster_members(client: Any) -> tuple[dict[str, str], str | None, bool | None]:
    """Return ``(node → online|offline, entry node, quorate)`` from ``/cluster/status``."""
    entries = normalize_list(await client.get("/cluster/status"))
    cluster = next((e for e in entries if e.get("type") == "cluster"), None)
    local = next((e for e in entries if e.get("type") == "node" and e.get("local")), None)
    quorate = bool(cluster.get("quorate")) if cluster else None
    return node_states(entries), (local.get("name") if local else None), quorate


def qdevice_votes(qdevice: dict[str, Any], warnings: list[str]) -> tuple[int, int]:
    """Return ``(expected, live)`` QDevice votes; a configured but disconnected QDevice is not live."""
    if not qdevice.get("configured"):
        return 0, 0
    status = qdevice.get("status")
    state = str(status.get("State", "")) if isinstance(status, dict) else ""
    if state.lower() == "connected":
        return 1, 1
    warnings.append(f"QDevice state is {state or 'unknown'!r}; its vote is not counted as live.")
    return 1, 0


def quorum_impact(
    members: dict[str, str], target: str, qdevice_expected: int, qdevice_live: int | None = None
) -> dict[str, Any]:
    """Estimate votes before/after powering off *target* (one vote per node plus the QDevice)."""
    live = qdevice_expected if qdevice_live is None else qdevice_live
    expected = len(members) + qdevice_expected
    needed = expected // 2 + 1
    online_now = sum(1 for state in members.values() if state == "online") + live
    online_after = online_now - (1 if members.get(target) == "online" else 0)
    return {
        "expected_votes": expected,
        "quorum_votes": needed,
        "online_votes_now": online_now,
        "online_votes_after": online_after,
        "quorate_after": online_after >= needed,
    }


async def _running_guests(client: Any, node: str, infra: frozenset[int], warnings: list[str]) -> list[dict]:
    running: list[dict[str, Any]] = []
    for guest_type in ("qemu", "lxc"):
        try:
            items = normalize_list(await client.get(f"/nodes/{node}/{guest_type}"))
        except Exception as exc:
            warnings.append(f"Could not list {guest_type} guests on {node}: {exc}")
            continue
        for item in items:
            if item.get("status") == "running":
                vmid = int(item.get("vmid", 0))
                running.append(
                    {"vmid": vmid, "name": item.get("name"), "guest_type": guest_type, "infra": vmid in infra}
                )
    return running


@write_tool_handler(
    "pve_shutdown_node",
    mutating=True,
    audit_fields=("node", "command", "reason", "allow_entry_host", "plan_only"),
)
async def pve_shutdown_node_impl(  # noqa: C901
    node: str,
    reason: str,
    confirm: bool = False,
    command: str = "shutdown",
    allow_entry_host: bool = False,
    plan_only: bool = False,
) -> str:
    """Shut down or reboot one node behind HA-policy, entry-node, and quorum guards."""
    if not plan_only:
        require_confirm(confirm)
    parsed = parse_model(ShutdownNodeInput, node=node, command=command, reason=reason)
    assert isinstance(parsed, ShutdownNodeInput)

    started = time.perf_counter()
    client = get_client()
    settings = get_settings()
    warnings: list[str] = []
    refusals: list[str] = []

    members, entry_node, quorate = await _cluster_members(client)
    if parsed.node not in members:
        raise ValueError(f"Unknown node {parsed.node!r}; cluster members: {sorted(members)}")
    target_online = members[parsed.node] == "online"
    if not target_online:
        refusals.append(f"{parsed.node} is already offline.")

    policy = parse_shutdown_policy(await client.get("/cluster/options"))
    if policy != HA_REQUIRED_SHUTDOWN_POLICY:
        refusals.append(
            f"ha.shutdown_policy is {policy!r}; {HA_REQUIRED_SHUTDOWN_POLICY!r} is required "
            + "(run ./deploy/proxmox.sh setup-cluster-ha)."
        )

    is_entry = parsed.node == entry_node
    peers_online = sorted(n for n, s in members.items() if s == "online" and n != parsed.node)
    if is_entry and not allow_entry_host:
        refusals.append(
            f"{parsed.node} is the API entry node; the MCP loses its connection. "
            + "Shut it down last with allow_entry_host=true."
        )
    if is_entry and peers_online:
        warnings.append(f"Peers still online {peers_online}; the entry node should go last.")

    qdevice = await qdevice_status(client, warnings)
    impact = quorum_impact(members, parsed.node, *qdevice_votes(qdevice, warnings))
    if quorate and not impact["quorate_after"]:
        warnings.append(
            f"Cluster loses quorum after this {parsed.command} "
            + f"({impact['online_votes_after']}/{impact['quorum_votes']} votes): /etc/pve becomes "
            + "read-only; only node-local operations work afterwards."
        )
        ha = await ha_placement(client, warnings)
        at_risk = ha.fence_risk(peers_online) if ha is not None else []
        if ha is None:
            refusals.append("Quorum would be lost and HA status is unreadable, so self-fencing cannot be ruled out.")
        elif at_risk:
            refusals.append(
                f"Quorum would be lost and {at_risk} have HA resources or an active LRM: they self-fence "
                + "(watchdog reset after 60 s). Move their HA resources away and wait for the LRM to go idle."
            )

    running: list[dict[str, Any]] = []
    if target_online:
        running = await _running_guests(client, parsed.node, settings.infra_vmids, warnings)
    if running:
        warnings.append(
            f"{len(running)} guest(s) still running on {parsed.node}; the node's own stop sequence "
            + "will shut them down. Prefer pve_stopall_guests / pve_shutdown_guest first."
        )
    infra_running = [g["vmid"] for g in running if g["infra"]]
    if infra_running:
        warnings.append(
            f"Infrastructure guest(s) {infra_running} (LAN router) stop with this node: "
            + "TrueNAS becomes unreachable. Shut TrueNAS down (delayed) before this call."
        )

    plan: dict[str, Any] = {
        "node": parsed.node,
        "command": parsed.command,
        "reason": parsed.reason,
        "entry_node": entry_node,
        "is_entry_node": is_entry,
        "peers_online": peers_online,
        "quorate": quorate,
        "ha_shutdown_policy": policy,
        "quorum_impact": impact,
        "running_guests": running,
        "refusals": refusals,
    }

    if plan_only:
        plan["would_execute"] = not refusals
        duration_ms = int((time.perf_counter() - started) * 1000)
        return ok_response("pve_shutdown_node", plan, duration_ms=duration_ms, warnings=warnings)

    if refusals:
        raise PveApiError(
            "Node power command refused: " + " ".join(refusals),
            code="PVE_POWER_GUARD",
            hint="Run with plan_only=true to see every check.",
            endpoint=f"/nodes/{parsed.node}/status",
        )

    api_lost = False
    try:
        await client.post(f"/nodes/{parsed.node}/status", data={"command": parsed.command})
    except PveApiError as exc:
        if not (is_entry and exc.code in API_LOST_ERROR_CODES):
            raise
        api_lost = True
        warnings.append(f"API connection dropped after {parsed.command} of the entry node (expected).")

    plan["submitted"] = True
    plan["api_lost"] = api_lost
    plan["next_step"] = (
        f"pve_wait_nodes_state(nodes=['{parsed.node}'], target='offline')"
        if parsed.command == "shutdown"
        else f"pve_wait_nodes_state(nodes=['{parsed.node}'], target='online')"
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_shutdown_node", plan, duration_ms=duration_ms, warnings=warnings)


@write_tool_handler("pve_wake_on_lan", mutating=True, audit_fields=("nodes", "all_offline"))
async def pve_wake_on_lan_impl(
    confirm: bool,
    nodes: list[str] | None = None,
    all_offline: bool = False,
) -> str:
    """Send WoL magic packets (from the API entry node) to offline cluster members."""
    require_confirm(confirm)
    parsed = parse_model(WakeOnLanInput, nodes=nodes, all_offline=all_offline)
    assert isinstance(parsed, WakeOnLanInput)

    started = time.perf_counter()
    client = get_client()
    warnings: list[str] = []

    members, entry_node, _ = await _cluster_members(client)
    if parsed.all_offline:
        targets = sorted(n for n, s in members.items() if s != "online")
        if not targets:
            warnings.append("No offline cluster members; nothing to wake.")
    else:
        targets = parsed.nodes or []
        unknown = [n for n in targets if n not in members]
        if unknown:
            raise ValueError(f"Unknown node(s) {unknown}; cluster members: {sorted(members)}")

    results: list[dict[str, Any]] = []
    for target in targets:
        if members[target] == "online":
            results.append({"node": target, "sent": False, "skipped": "already online"})
            continue
        try:
            mac = await client.post(f"/nodes/{target}/wakeonlan")
            results.append({"node": target, "sent": True, "mac": mac})
        except PveApiError as exc:
            entry: dict[str, Any] = {"node": target, "sent": False, "error": str(exc)}
            if any(key in str(exc).lower() for key in ("wakeonlan", "wake on lan", "mac")):
                entry["hint"] = WOL_MAC_HINT
            results.append(entry)
            warnings.append(f"WoL for {target} failed: {exc}")

    sent = [r["node"] for r in results if r.get("sent")]
    failed = [r for r in results if "error" in r]
    if failed and not sent:
        raise PveApiError(
            f"Wake-on-LAN failed for {[r['node'] for r in failed]}: {failed[0]['error']}",
            code="PVE_WOL_FAILED",
            hint=failed[0].get("hint") or WOL_MAC_HINT,
        )

    data = {
        "sent_from": entry_node,
        "sent": sent,
        "results": results,
        "next_step": f"pve_wait_nodes_state(nodes={sent}, target='online')" if sent else None,
    }
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_wake_on_lan", data, duration_ms=duration_ms, warnings=warnings)
