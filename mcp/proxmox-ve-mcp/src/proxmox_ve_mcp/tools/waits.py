"""Bounded wait MCP tools for tasks and node power state."""

import time
from typing import Any

from proxmox_ve_mcp.client.tasks import parse_upid_node, task_succeeded, wait_for_nodes_state, wait_for_task
from proxmox_ve_mcp.context import get_client
from proxmox_ve_mcp.tools.helpers import normalize_list, parse_model
from proxmox_ve_mcp.tools.response import ok_response, tool_handler
from proxmox_ve_mcp.tools.schemas import WaitForTaskInput, WaitNodesStateInput

TASK_LOG_TAIL_LINES = 20


@tool_handler("pve_wait_for_task")
async def pve_wait_for_task_impl(upid: str, timeout_s: float = 120.0) -> str:
    """Wait up to *timeout_s* for a task; returns ``finished=false`` (not an error) on timeout."""
    parsed = parse_model(WaitForTaskInput, upid=upid, timeout_s=timeout_s)
    assert isinstance(parsed, WaitForTaskInput)
    node = parse_upid_node(parsed.upid)
    assert node is not None

    started = time.perf_counter()
    client = get_client()
    warnings: list[str] = []
    status: dict[str, Any]
    try:
        status = await wait_for_task(client, node, parsed.upid, timeout_sec=parsed.timeout_s)
        finished = True
    except TimeoutError:
        status = await client.get(f"/nodes/{node}/tasks/{parsed.upid}/status") or {}
        finished = False
        warnings.append(f"Task still running after {parsed.timeout_s:g}s; call pve_wait_for_task again.")

    log_tail: list[Any] = []
    try:
        log = normalize_list(await client.get(f"/nodes/{node}/tasks/{parsed.upid}/log", params={"limit": 500}))
        log_tail = [line.get("t") for line in log[-TASK_LOG_TAIL_LINES:]]
    except Exception as exc:
        warnings.append(f"Could not load task log: {exc}")

    succeeded = task_succeeded(status) if finished else None
    if finished and not succeeded:
        warnings.append(f"Task finished with exitstatus {status.get('exitstatus')!r}.")

    data = {
        "upid": parsed.upid,
        "node": node,
        "finished": finished,
        "succeeded": succeeded,
        "status": status.get("status"),
        "exitstatus": status.get("exitstatus"),
        "log_tail": log_tail,
    }
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_wait_for_task", data, duration_ms=duration_ms, warnings=warnings)


@tool_handler("pve_wait_nodes_state")
async def pve_wait_nodes_state_impl(
    target: str,
    nodes: list[str] | None = None,
    timeout_s: float = 120.0,
) -> str:
    """Wait up to *timeout_s* for nodes to reach *target*; API loss counts as offline."""
    parsed = parse_model(WaitNodesStateInput, target=target, nodes=nodes, timeout_s=timeout_s)
    assert isinstance(parsed, WaitNodesStateInput)

    started = time.perf_counter()
    result = await wait_for_nodes_state(get_client(), parsed.nodes, parsed.target, timeout_sec=parsed.timeout_s)
    warnings: list[str] = []
    if result["api_lost"]:
        warnings.append(
            f"API host stopped answering ({result.get('api_error')}); expected after the entry node shuts down. "
            "Unconfirmed nodes are reported as offline_assumed."
        )
    elif not result["reached"]:
        warnings.append(
            f"Still waiting on {', '.join(result['pending'])} after {parsed.timeout_s:g}s; "
            "call pve_wait_nodes_state again."
        )
    result["target"] = parsed.target
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_wait_nodes_state", result, duration_ms=duration_ms, warnings=warnings)
