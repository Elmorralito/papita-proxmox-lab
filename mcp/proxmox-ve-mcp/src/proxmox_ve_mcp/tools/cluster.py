"""Cluster-level MCP tool implementations."""

import time
from typing import Any

from proxmox_ve_mcp.constants import BASH_ONLY_WORKFLOWS
from proxmox_ve_mcp.context import get_client, get_settings
from proxmox_ve_mcp.tools.helpers import normalize_list, parse_model
from proxmox_ve_mcp.tools.response import ok_response, tool_handler
from proxmox_ve_mcp.tools.schemas import ListResourcesInput, ListTasksInput, validate_node_name


@tool_handler("pve_get_version")
async def pve_get_version_impl() -> str:
    """Get Proxmox VE version and release (smoke test for API auth and TLS)."""
    started = time.perf_counter()
    client = get_client()
    data = await client.get("/version")
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_get_version", data, duration_ms=duration_ms)


@tool_handler("pve_list_nodes")
async def pve_list_nodes_impl() -> str:
    """List cluster members with online/offline status."""
    started = time.perf_counter()
    client = get_client()
    data = await client.get("/cluster/resources", params={"type": "node"})
    nodes = normalize_list(data)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pve_list_nodes",
        {"nodes": nodes, "count": len(nodes)},
        duration_ms=duration_ms,
    )


@tool_handler("pve_get_cluster_config_nodes")
async def pve_get_cluster_config_nodes_impl() -> str:
    """Cluster node config including ring0_addr; maps deploy/proxmox.sh local-node."""
    started = time.perf_counter()
    client = get_client()
    settings = get_settings()
    data = normalize_list(await client.get("/cluster/config/nodes"))
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pve_get_cluster_config_nodes",
        {
            "nodes": data,
            "count": len(data),
            "api_entry_host": settings.host,
            "note": (
                "api_entry_host is PVE_HOST (any online member). "
                "Compare node names to ring0_addr; MCP v1 does not run pvecm for (local)."
            ),
        },
        duration_ms=duration_ms,
    )


@tool_handler("pve_get_cluster_options")
async def pve_get_cluster_options_impl() -> str:
    """Read datacenter cluster options (mailto, mailfrom)."""
    started = time.perf_counter()
    client = get_client()
    data = await client.get("/cluster/options")
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_get_cluster_options", data, duration_ms=duration_ms)


@tool_handler("pve_list_tasks")
async def pve_list_tasks_impl(
    statusfilter: str | None = None,
    start: int | None = None,
    limit: int | None = None,
) -> str:
    """List cluster tasks with optional status filter."""
    parsed = parse_model(
        ListTasksInput,
        statusfilter=statusfilter,
        start=start,
        limit=limit,
    )
    assert isinstance(parsed, ListTasksInput)

    started = time.perf_counter()
    client = get_client()
    params: dict[str, Any] = {}
    if parsed.statusfilter:
        params["statusfilter"] = parsed.statusfilter
    if parsed.start is not None:
        params["start"] = parsed.start
    if parsed.limit is not None:
        params["limit"] = parsed.limit

    data = normalize_list(await client.get("/cluster/tasks", params=params or None))
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pve_list_tasks",
        {"tasks": data, "count": len(data)},
        duration_ms=duration_ms,
    )


@tool_handler("pve_get_task_log")
async def pve_get_task_log_impl(node: str, upid: str) -> str:
    """Task log for a UPID."""
    started = time.perf_counter()
    validate_node_name(node)
    if not upid.startswith("UPID:"):
        raise ValueError("upid must start with UPID:")
    client = get_client()
    data = await client.get(f"/nodes/{node}/tasks/{upid}/log")
    log_lines = normalize_list(data) if isinstance(data, (list, dict)) else data
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pve_get_task_log",
        {"node": node, "upid": upid, "log": log_lines},
        duration_ms=duration_ms,
    )


@tool_handler("pve_list_resources")
async def pve_list_resources_impl(
    type: str | None = None,
    node: str | None = None,
    start: int | None = None,
    limit: int | None = None,
) -> str:
    """List cluster resources with filters."""
    parsed = parse_model(
        ListResourcesInput,
        type=type,
        node=node,
        start=start,
        limit=limit,
    )
    assert isinstance(parsed, ListResourcesInput)

    started = time.perf_counter()
    client = get_client()
    params: dict[str, Any] = {}
    if parsed.type:
        params["type"] = parsed.type
    if parsed.start is not None:
        params["start"] = parsed.start
    if parsed.limit is not None:
        params["limit"] = parsed.limit

    data = await client.get("/cluster/resources", params=params or None)
    resources = normalize_list(data)
    if parsed.node:
        resources = [item for item in resources if item.get("node") == parsed.node]

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pve_list_resources",
        {"resources": resources, "count": len(resources)},
        duration_ms=duration_ms,
    )


@tool_handler("pve_cluster_health")
async def pve_cluster_health_impl() -> str:
    """Cluster health summary; approximate quorum (no pvecm in v1)."""
    started = time.perf_counter()
    client = get_client()
    settings = get_settings()
    warnings: list[str] = []

    nodes_data = normalize_list(await client.get("/cluster/resources", params={"type": "node"}))
    online = [n for n in nodes_data if n.get("status") == "online"]
    offline = [n for n in nodes_data if n.get("status") != "online"]

    config_nodes: list[dict[str, Any]] = []
    try:
        config_raw = await client.get("/cluster/config/nodes")
        config_nodes = normalize_list(config_raw)
    except Exception as exc:
        warnings.append(f"Could not load /cluster/config/nodes: {exc}")

    expected_count = len(config_nodes) if config_nodes else len(nodes_data)
    online_count = len(online)
    approx_quorate = 0 < expected_count <= online_count

    if offline:
        warnings.append("Offline nodes: " + ", ".join(n.get("node", "?") for n in offline))
    if config_nodes and online_count < expected_count:
        warnings.append(
            "Approximate quorum: not all configured nodes are online "
            "(true quorum requires pvecm; not available via REST in v1)."
        )

    summary = {
        "online_count": online_count,
        "offline_count": len(offline),
        "expected_node_count": expected_count,
        "approx_all_nodes_online": approx_quorate,
        "online_nodes": [n.get("node") for n in online],
        "offline_nodes": [n.get("node") for n in offline],
        "api_entry_host": settings.host,
        "bash_only_workflows": BASH_ONLY_WORKFLOWS,
    }
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_cluster_health", summary, duration_ms=duration_ms, warnings=warnings)
