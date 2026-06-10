"""Ceph read-only MCP tools."""

import time
from typing import Any

from proxmox_ve_mcp.client.errors import PveApiError
from proxmox_ve_mcp.context import get_client
from proxmox_ve_mcp.tools.helpers import normalize_list
from proxmox_ve_mcp.tools.response import ok_response, tool_handler
from proxmox_ve_mcp.tools.schemas import validate_node_name


@tool_handler("pve_get_ceph_status")
async def pve_get_ceph_status_impl(node: str | None = None) -> str:
    """Ceph health summary (read-only); OSD startup is manual — see runbook_ref in meta."""
    started = time.perf_counter()
    client = get_client()
    warnings: list[str] = []

    if node:
        validate_node_name(node)

    data: Any = None
    try:
        data = await client.get("/cluster/ceph/status")
    except PveApiError as cluster_exc:
        warnings.append(f"/cluster/ceph/status unavailable: {cluster_exc}")
        target_node = node
        if not target_node:
            nodes = normalize_list(await client.get("/cluster/resources", params={"type": "node"}))
            online = [n.get("node") for n in nodes if n.get("status") == "online"]
            target_node = online[0] if online else None
        if target_node:
            data = await client.get(f"/nodes/{target_node}/ceph/status")
        else:
            raise

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_get_ceph_status", data, duration_ms=duration_ms, warnings=warnings)


@tool_handler("pve_list_ceph_osds")
async def pve_list_ceph_osds_impl(node: str) -> str:
    """List Ceph OSDs on a node."""
    started = time.perf_counter()
    validate_node_name(node)
    client = get_client()
    data = await client.get(f"/nodes/{node}/ceph/osd")
    osds = normalize_list(data)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pve_list_ceph_osds",
        {"node": node, "osds": osds, "count": len(osds)},
        duration_ms=duration_ms,
    )
