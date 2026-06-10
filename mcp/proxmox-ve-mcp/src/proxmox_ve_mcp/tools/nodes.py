"""Node and guest read MCP tool implementations."""

import time
from typing import Any

from proxmox_ve_mcp.client.errors import PveApiError
from proxmox_ve_mcp.context import get_client
from proxmox_ve_mcp.tools.helpers import normalize_list, parse_model
from proxmox_ve_mcp.tools.response import ok_response, tool_handler
from proxmox_ve_mcp.tools.schemas import GuestRefInput, ListGuestsInput, validate_node_name


@tool_handler("pve_get_node_status")
async def pve_get_node_status_impl(node: str) -> str:
    """Node CPU, memory, uptime."""
    started = time.perf_counter()
    validate_node_name(node)
    client = get_client()
    data = await client.get(f"/nodes/{node}/status")
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_get_node_status", data, duration_ms=duration_ms)


@tool_handler("pve_list_guests")
async def pve_list_guests_impl(node: str | None = None) -> str:
    """Unified VM/CT list with guest_type tag."""
    parsed = parse_model(ListGuestsInput, node=node)
    assert isinstance(parsed, ListGuestsInput)

    started = time.perf_counter()
    client = get_client()
    warnings: list[str] = []

    if parsed.node is None:
        resources = await client.get("/cluster/resources")
        items = normalize_list(resources)
        guests = [_resource_to_guest(item) for item in items if item.get("type") in {"qemu", "lxc"}]
    else:
        guests = []
        for guest_type, path in (("qemu", "qemu"), ("lxc", "lxc")):
            try:
                raw = await client.get(f"/nodes/{parsed.node}/{path}")
                for item in normalize_list(raw):
                    guests.append({**item, "guest_type": guest_type, "node": parsed.node})
            except PveApiError as exc:
                warnings.append(f"Could not list {guest_type} on {parsed.node}: {exc}")

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pve_list_guests",
        {"guests": guests, "count": len(guests)},
        duration_ms=duration_ms,
        warnings=warnings,
    )


@tool_handler("pve_get_guest_status")
async def pve_get_guest_status_impl(node: str, vmid: int, guest_type: str) -> str:
    """Runtime status for a VM or CT."""
    ref = parse_model(GuestRefInput, node=node, vmid=vmid, guest_type=guest_type)
    assert isinstance(ref, GuestRefInput)

    started = time.perf_counter()
    client = get_client()
    data = await client.get(f"/nodes/{ref.node}/{ref.guest_type}/{ref.vmid}/status/current")
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pve_get_guest_status",
        {
            "node": ref.node,
            "vmid": ref.vmid,
            "guest_type": ref.guest_type,
            "status": data,
        },
        duration_ms=duration_ms,
    )


def _resource_to_guest(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a cluster resource entry into a guest summary dict."""
    guest_type = item.get("type", "")
    return {
        "vmid": item.get("vmid"),
        "name": item.get("name"),
        "node": item.get("node"),
        "guest_type": guest_type,
        "status": item.get("status"),
        "maxcpu": item.get("maxcpu"),
        "maxmem": item.get("maxmem"),
        "mem": item.get("mem"),
        "cpu": item.get("cpu"),
        "disk": item.get("disk"),
        "uptime": item.get("uptime"),
    }
