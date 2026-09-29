"""Ordered, resumable full-cluster shutdown (``pve_shutdown_cluster``).

Each call re-reads live cluster state, runs the next stage, and waits within a bounded
budget; re-calling with the same arguments resumes (in-flight tasks are reused, not
resubmitted). Stage order: stop guests (peers via ``stopall``, entry node per guest except
``keep_running_vmids``) → shut down peers while quorate → ``ready_for_nas`` (agent runs the
delayed ``truenas_shutdown``) → entry node shutdown when ``include_entry_node=true`` and the
peers were already offline when the call started.

HA-managed guests are never stopped per guest (that flips their HA requested state to
``stopped``); nodes hosting them get per-guest shutdowns for the rest, and node shutdown with
``ha.shutdown_policy=freeze`` stops and later restores the HA guests.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from proxmox_ve_mcp.client.errors import PveApiError
from proxmox_ve_mcp.client.http import PveClient
from proxmox_ve_mcp.client.tasks import (
    node_states,
    parse_upid_node,
    task_succeeded,
    wait_for_nodes_state,
    wait_for_task,
)
from proxmox_ve_mcp.constants import API_LOST_ERROR_CODES, HA_REQUIRED_SHUTDOWN_POLICY
from proxmox_ve_mcp.context import get_client, get_settings
from proxmox_ve_mcp.tools.ha import HaPlacement, ha_placement, parse_shutdown_policy
from proxmox_ve_mcp.tools.helpers import normalize_list, parse_model, require_confirm
from proxmox_ve_mcp.tools.response import ok_response, write_tool_handler
from proxmox_ve_mcp.tools.schemas import ShutdownClusterInput

STAGE_BLOCKED = "blocked"
STAGE_STOP_GUESTS = "stop_guests"
STAGE_SHUTDOWN_PEERS = "shutdown_peers"
STAGE_READY_FOR_NAS = "ready_for_nas"
STAGE_SHUTDOWN_ENTRY = "shutdown_entry"
STAGE_ENTRY_SUBMITTED = "entry_shutdown_submitted"
_TERMINAL_STAGES = {STAGE_BLOCKED, STAGE_READY_FOR_NAS, STAGE_SHUTDOWN_ENTRY}
_GUEST_TASK_TYPES = {"qmshutdown", "vzshutdown", "qmstop", "vzstop"}


@dataclass
class ClusterState:
    """Live snapshot used to pick the next stage."""

    members: dict[str, str]
    entry: str | None
    entry_ip: str | None = None
    quorate: bool | None = None
    running: list[dict[str, Any]] = field(default_factory=list)
    ha: HaPlacement | None = None

    @property
    def peers_online(self) -> list[str]:
        """Online members other than the entry node."""
        return sorted(n for n, s in self.members.items() if s == "online" and n != self.entry)

    @property
    def ha_vmids(self) -> frozenset[int]:
        """HA-managed VMIDs (left to node shutdown + ``freeze``; never stopped per guest)."""
        return self.ha.vmids if self.ha else frozenset()


def next_stage(
    state: ClusterState,
    keep: frozenset[int],
    include_entry: bool,
    skip_guest_nodes: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Pure stage selection from *state* (no I/O)."""
    misplaced = [g for g in state.running if g["vmid"] in keep and g["node"] != state.entry]
    if misplaced:
        where = ", ".join(f"{g['vmid']}@{g['node']}" for g in misplaced)
        return {
            "stage": STAGE_BLOCKED,
            "actions": [],
            "reason": f"keep_running guest(s) {where} run on a peer; migrate them to the entry node {state.entry}.",
        }

    ha_vmids = state.ha_vmids
    actions: list[dict[str, Any]] = []
    for node in state.peers_online:
        if node in skip_guest_nodes:
            continue
        on_node = [g for g in state.running if g["node"] == node]
        plain = [g for g in on_node if g["vmid"] not in ha_vmids]
        if plain and len(plain) == len(on_node):
            actions.append({"op": "stopall", "node": node})
        else:
            actions.extend({"op": "shutdown_guest", **g} for g in plain)
    if state.entry not in skip_guest_nodes:
        for guest in state.running:
            if guest["node"] == state.entry and guest["vmid"] not in keep and guest["vmid"] not in ha_vmids:
                actions.append({"op": "shutdown_guest", **guest})
    if actions:
        return {"stage": STAGE_STOP_GUESTS, "actions": actions}
    if state.peers_online:
        return {
            "stage": STAGE_SHUTDOWN_PEERS,
            "actions": [{"op": "shutdown_node", "node": n} for n in state.peers_online],
        }
    if include_entry:
        return {"stage": STAGE_SHUTDOWN_ENTRY, "actions": [{"op": "shutdown_node", "node": state.entry}]}
    return {"stage": STAGE_READY_FOR_NAS, "actions": []}


def simulate(state: ClusterState, keep: frozenset[int], include_entry: bool) -> list[dict[str, Any]]:
    """Project every remaining stage assuming each action succeeds (``plan_only``)."""
    members = dict(state.members)
    running = list(state.running)
    stages: list[dict[str, Any]] = []
    for _ in range(len(_TERMINAL_STAGES) + 2):
        stage = next_stage(ClusterState(members, state.entry, running=running, ha=state.ha), keep, include_entry)
        stages.append(stage)
        if stage["stage"] in _TERMINAL_STAGES:
            break
        if stage["stage"] == STAGE_STOP_GUESTS:
            nodes = {a["node"] for a in stage["actions"] if a["op"] == "stopall"}
            vmids = {a["vmid"] for a in stage["actions"] if a["op"] == "shutdown_guest"}
            running = [g for g in running if g["node"] not in nodes and g["vmid"] not in vmids]
        else:
            targets = {a["node"] for a in stage["actions"]}
            members = {n: ("offline" if n in targets else s) for n, s in members.items()}
    return stages


async def _snapshot(client: Any, warnings: list[str]) -> ClusterState:
    entries = normalize_list(await client.get("/cluster/status"))
    cluster = next((e for e in entries if e.get("type") == "cluster"), None)
    local = next((e for e in entries if e.get("type") == "node" and e.get("local")), None)
    resources = normalize_list(await client.get("/cluster/resources", params={"type": "vm"}))
    running = [
        {
            "vmid": int(r.get("vmid", 0)),
            "node": r.get("node"),
            "guest_type": r.get("type"),
            "name": r.get("name"),
        }
        for r in resources
        if r.get("status") == "running" and r.get("type") in {"qemu", "lxc"}
    ]
    return ClusterState(
        members=node_states(entries),
        entry=local.get("name") if local else None,
        entry_ip=local.get("ip") if local else None,
        quorate=bool(cluster.get("quorate")) if cluster else None,
        running=running,
        ha=await ha_placement(client, warnings),
    )


async def _active_tasks(client: Any, warnings: list[str]) -> dict[tuple[str, str], str]:
    """In-flight stopall / guest shutdown tasks, keyed so re-calls reuse them."""
    try:
        tasks = normalize_list(await client.get("/cluster/tasks"))
    except Exception as exc:
        warnings.append(f"Could not read /cluster/tasks (in-flight tasks not reused): {exc}")
        return {}
    active: dict[tuple[str, str], str] = {}
    for task in tasks:
        if task.get("endtime") or task.get("status"):
            continue
        if task.get("type") == "stopall":
            active[("stopall", str(task.get("node")))] = str(task.get("upid"))
        elif task.get("type") in _GUEST_TASK_TYPES:
            active[("guest", str(task.get("id")))] = str(task.get("upid"))
    return active


async def _execute(  # noqa: C901
    client: Any,
    stage: dict[str, Any],
    state: ClusterState,
    guest_timeout_s: int,
    warnings: list[str],
) -> list[dict[str, Any]]:
    active = await _active_tasks(client, warnings) if stage["stage"] == STAGE_STOP_GUESTS else {}
    results: list[dict[str, Any]] = []
    for action in stage["actions"]:
        result = dict(action)
        try:
            if action["op"] == "stopall":
                key = ("stopall", action["node"])
                result["reused"] = key in active
                result["upid"] = active.get(key) or await client.post(
                    f"/nodes/{action['node']}/stopall",
                    data={"timeout": guest_timeout_s},
                    timeout=PveClient.long_timeout(),
                )
            elif action["op"] == "shutdown_guest":
                key = ("guest", str(action["vmid"]))
                result["reused"] = key in active
                result["upid"] = active.get(key) or await client.post(
                    f"/nodes/{action['node']}/{action['guest_type']}/{action['vmid']}/status/shutdown",
                    data={"timeout": guest_timeout_s, "forceStop": 1},
                    timeout=PveClient.long_timeout(),
                )
            else:
                await client.post(f"/nodes/{action['node']}/status", data={"command": "shutdown"})
                result["submitted"] = True
        except PveApiError as exc:
            if action["op"] == "shutdown_node" and action["node"] == state.entry and exc.code in API_LOST_ERROR_CODES:
                result["submitted"] = True
                result["api_lost"] = True
                warnings.append("API connection dropped after the entry node shutdown (expected).")
            elif action["op"] == "shutdown_node" and exc.code == "PVE_TIMEOUT":
                result["submitted"] = True
                result["unconfirmed"] = True
                warnings.append(f"Shutdown request for {action['node']} timed out; waiting to see if it powers off.")
            else:
                result["error"] = str(exc)
                warnings.append(f"{action['op']} on {action['node']} failed: {exc}")
        results.append(result)
    return results


async def _wait(
    client: Any, stage: dict[str, Any], results: list[dict[str, Any]], budget_s: float, warnings: list[str]
) -> dict[str, Any]:
    if budget_s <= 0:
        return {"timed_out": True}
    if stage["stage"] == STAGE_SHUTDOWN_PEERS:
        nodes = [r["node"] for r in results if r.get("submitted")]
        if not nodes:
            return {"timed_out": False, "reached": False}
        try:
            outcome = await wait_for_nodes_state(
                client, nodes, "offline", timeout_sec=budget_s, assume_offline_on_api_loss=False
            )
        except PveApiError as exc:
            warnings.append(f"Lost the API on the entry node while waiting for peers to power off: {exc}")
            return {"timed_out": True, "api_error": exc.code}
        return {"timed_out": not outcome["reached"], **outcome}

    upids = [str(r["upid"]) for r in results if isinstance(r.get("upid"), str)]
    statuses = await asyncio.gather(
        *(wait_for_task(client, parse_upid_node(u) or "", u, timeout_sec=budget_s) for u in upids),
        return_exceptions=True,
    )
    tasks: list[dict[str, Any]] = []
    timed_out = False
    for upid, status in zip(upids, statuses):
        if isinstance(status, TimeoutError):
            timed_out = True
            tasks.append({"upid": upid, "finished": False})
        elif isinstance(status, BaseException):
            tasks.append({"upid": upid, "finished": False, "error": str(status)})
        else:
            tasks.append({"upid": upid, "finished": True, "succeeded": task_succeeded(status)})
    return {"timed_out": timed_out, "tasks": tasks}


def _next_steps(stage: str, state: ClusterState, reason: str) -> list[str]:
    entry_ip = f'"{state.entry_ip}"' if state.entry_ip else "<entry node IP>"
    if stage == STAGE_READY_FOR_NAS:
        return [
            f'truenas_shutdown(reason="{reason}", delay_s=300, expected_clients=[{entry_ip}], confirm=true)',
            f"pve_shutdown_cluster(include_entry_node=true, confirm=true, ...) "
            f"or pve_shutdown_node(node='{state.entry}', allow_entry_host=true, confirm=true, ...)",
        ]
    if stage == STAGE_ENTRY_SUBMITTED:
        return ["Lab powering off. Cold start later: ./deploy/proxmox.sh wake-lab --ip-address 172.16.0.99"]
    return ["Call pve_shutdown_cluster again with the same arguments to resume."]


@write_tool_handler(
    "pve_shutdown_cluster",
    mutating=True,
    audit_fields=("reason", "include_entry_node", "keep_running_vmids", "plan_only", "continue_on_error"),
)
async def pve_shutdown_cluster_impl(  # noqa: C901  # pylint: disable=too-many-arguments,too-many-locals
    reason: str,
    confirm: bool = False,
    plan_only: bool = False,
    include_entry_node: bool = False,
    keep_running_vmids: list[int] | None = None,
    guest_timeout_s: int = 120,
    continue_on_error: bool = False,
    wait_for_completion: bool = True,
    timeout_s: float = 120.0,
) -> str:
    """Ordered cluster shutdown; resumable across calls, bounded by *timeout_s* per call."""
    if not plan_only:
        require_confirm(confirm)
    parsed = parse_model(
        ShutdownClusterInput,
        reason=reason,
        keep_running_vmids=keep_running_vmids,
        guest_timeout_s=guest_timeout_s,
        timeout_s=timeout_s,
    )
    assert isinstance(parsed, ShutdownClusterInput)

    started = time.perf_counter()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + parsed.timeout_s
    client = get_client()
    keep = frozenset(parsed.keep_running_vmids) if parsed.keep_running_vmids is not None else get_settings().infra_vmids
    warnings: list[str] = []
    history: list[dict[str, Any]] = []

    state = await _snapshot(client, warnings)
    ha = state.ha
    policy = parse_shutdown_policy(await client.get("/cluster/options"))
    refusals: list[str] = []
    if policy != HA_REQUIRED_SHUTDOWN_POLICY:
        refusals.append(f"ha.shutdown_policy is {policy!r}; {HA_REQUIRED_SHUTDOWN_POLICY!r} is required.")
    if state.entry is None:
        refusals.append("Could not resolve the API entry node (no local=1 entry in /cluster/status).")
    if state.peers_online and ha is None:
        refusals.append("HA status is unreadable, so HA guests and entry-node fencing cannot be checked.")
    if state.peers_online and ha is not None and ha.fence_risk([state.entry or ""]):
        refusals.append(
            f"Entry node {state.entry} has HA resources or an active LRM and self-fences (watchdog reset "
            + "after 60 s) once the peers are down; move its HA resources to a peer and wait for its LRM "
            + "to go idle (pve_get_ha_status)."
        )
    if state.peers_online and state.quorate is False:
        warnings.append("Cluster is not quorate; peer shutdown proceeds but /etc/pve is read-only.")
    if state.ha_vmids:
        warnings.append(
            f"HA-managed guest(s) {sorted(state.ha_vmids)} are not stopped per guest (that would set their "
            + "HA requested state to 'stopped'); node shutdown with ha.shutdown_policy=freeze handles them."
        )
    entry_allowed = include_entry_node and not state.peers_online
    if include_entry_node and not entry_allowed:
        warnings.append(
            "include_entry_node deferred: peers were online at call start. Submit the delayed "
            + "truenas_shutdown at ready_for_nas, then call again with include_entry_node=true."
        )

    def respond(stage: str, done: bool) -> str:
        data = {
            "stage": stage,
            "done": done,
            "entry_node": state.entry,
            "keep_running_vmids": sorted(keep),
            "ha_shutdown_policy": policy,
            "peers_online": state.peers_online,
            "running_guests": state.running,
            "ha_managed_vmids": sorted(state.ha_vmids),
            "history": history,
            "next_steps": _next_steps(stage, state, parsed.reason),
        }
        duration_ms = int((time.perf_counter() - started) * 1000)
        return ok_response("pve_shutdown_cluster", data, duration_ms=duration_ms, warnings=warnings)

    if plan_only:
        stages = simulate(state, keep, entry_allowed)
        blocked = [s["reason"] for s in stages if s["stage"] == STAGE_BLOCKED]
        history.extend({"stage": s["stage"], "actions": s["actions"]} for s in stages)
        warnings.extend(f"Refusal: {r}" for r in refusals + blocked)
        return respond("plan", done=False)

    if refusals:
        raise PveApiError(
            "Cluster shutdown refused: " + " ".join(refusals),
            code="PVE_POWER_GUARD",
            hint="Run with plan_only=true; apply freeze via ./deploy/proxmox.sh setup-cluster-ha.",
        )

    attempted_stopall: set[str] = set()
    attempted_shutdown: set[str] = set()
    attempted_vmids: set[int] = set()
    skip_guest_nodes: set[str] = set()
    while True:
        stage = next_stage(state, keep, entry_allowed, frozenset(skip_guest_nodes))
        if stage["stage"] == STAGE_BLOCKED:
            raise PveApiError(stage["reason"], code="PVE_POWER_GUARD")
        if stage["stage"] == STAGE_READY_FOR_NAS:
            return respond(STAGE_READY_FOR_NAS, done=True)

        stuck = [
            a
            for a in stage["actions"]
            if (a["op"] == "stopall" and a["node"] in attempted_stopall)
            or (a["op"] == "shutdown_guest" and a["vmid"] in attempted_vmids)
            or (a["op"] == "shutdown_node" and a["node"] in attempted_shutdown)
        ]
        if stuck:
            detail = ", ".join(f"{a['op']}:{a.get('vmid') or a['node']}" for a in stuck)
            if stage["stage"] != STAGE_STOP_GUESTS or not continue_on_error:
                raise PveApiError(
                    f"Cluster shutdown aborted at {stage['stage']}: still pending after an attempt ({detail}).",
                    code="PVE_SHUTDOWN_ABORTED",
                    pve_errors={"history": history},
                    hint="Inspect with pve_list_guests / pve_get_task_log; pve_stop_guest for hung guests; "
                    + "continue_on_error=true lets node shutdown stop remaining guests.",
                )
            warnings.append(f"Guests still running after stop ({detail}); continuing (continue_on_error=true).")
            skip_guest_nodes.update(a["node"] for a in stuck)
            continue

        if stage["stage"] == STAGE_SHUTDOWN_ENTRY:
            warnings.append(
                "Entry node shutdown: the LAN router guest stops and TrueNAS becomes unreachable; "
                + "the delayed truenas_shutdown must already be submitted."
            )
        results = await _execute(client, stage, state, parsed.guest_timeout_s, warnings)
        history.append({"stage": stage["stage"], "results": results})
        if stage["stage"] == STAGE_SHUTDOWN_ENTRY:
            return respond(STAGE_ENTRY_SUBMITTED, done=True)
        attempted_stopall.update(a["node"] for a in stage["actions"] if a["op"] == "stopall")
        attempted_shutdown.update(a["node"] for a in stage["actions"] if a["op"] == "shutdown_node")
        attempted_vmids.update(a["vmid"] for a in stage["actions"] if a["op"] == "shutdown_guest")

        if not wait_for_completion:
            return respond(stage["stage"], done=False)
        outcome = await _wait(client, stage, results, deadline - loop.time(), warnings)
        history[-1]["wait"] = outcome
        if outcome.get("timed_out") or loop.time() >= deadline:
            warnings.append(f"Time budget ({parsed.timeout_s:.0f}s) used during {stage['stage']}; re-call to resume.")
            return respond(stage["stage"], done=False)
        state = await _snapshot(client, warnings)
        state.ha = state.ha or ha
