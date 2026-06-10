"""Guest config and mutating MCP tools."""

import time
from typing import Any

from proxmox_ve_mcp.client.http import PveClient
from proxmox_ve_mcp.client.tasks import wait_for_task
from proxmox_ve_mcp.context import get_client
from proxmox_ve_mcp.tools.helpers import parse_model, redact_config, require_confirm
from proxmox_ve_mcp.tools.response import ok_response, tool_handler, write_tool_handler
from proxmox_ve_mcp.tools.schemas import GuestRefInput, validate_node_name


@tool_handler("pve_get_guest_config")
async def pve_get_guest_config_impl(node: str, vmid: int, guest_type: str) -> str:
    """Guest configuration with secrets redacted."""
    ref = parse_model(GuestRefInput, node=node, vmid=vmid, guest_type=guest_type)
    assert isinstance(ref, GuestRefInput)

    started = time.perf_counter()
    client = get_client()
    raw = await client.get(f"/nodes/{ref.node}/{ref.guest_type}/{ref.vmid}/config")
    config = redact_config(raw)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pve_get_guest_config",
        {"node": ref.node, "vmid": ref.vmid, "guest_type": ref.guest_type, "config": config},
        duration_ms=duration_ms,
    )


@write_tool_handler(
    "pve_start_guest",
    mutating=True,
    audit_fields=("node", "vmid", "guest_type"),
)
async def pve_start_guest_impl(
    node: str,
    vmid: int,
    guest_type: str,
    confirm: bool,
    wait_for_completion: bool = False,
) -> str:
    """Start a VM or CT."""
    require_confirm(confirm)
    ref = parse_model(GuestRefInput, node=node, vmid=vmid, guest_type=guest_type)
    assert isinstance(ref, GuestRefInput)

    started = time.perf_counter()
    client = get_client()
    upid = await client.post(f"/nodes/{ref.node}/{ref.guest_type}/{ref.vmid}/status/start")
    result: dict[str, Any] = {
        "node": ref.node,
        "vmid": ref.vmid,
        "guest_type": ref.guest_type,
        "upid": upid,
    }

    if wait_for_completion and isinstance(upid, str):
        result["task"] = await wait_for_task(client, ref.node, upid)

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_start_guest", result, duration_ms=duration_ms)


@write_tool_handler(
    "pve_shutdown_guest",
    mutating=True,
    audit_fields=("node", "vmid", "guest_type"),
)
async def pve_shutdown_guest_impl(
    node: str,
    vmid: int,
    guest_type: str,
    confirm: bool,
    timeout: int = 60,
    wait_for_completion: bool = False,
) -> str:
    """ACPI shutdown for a VM or CT."""
    require_confirm(confirm)
    ref = parse_model(GuestRefInput, node=node, vmid=vmid, guest_type=guest_type)
    assert isinstance(ref, GuestRefInput)

    started = time.perf_counter()
    client = get_client()
    upid = await client.post(
        f"/nodes/{ref.node}/{ref.guest_type}/{ref.vmid}/status/shutdown",
        data={"timeout": timeout},
        timeout=PveClient.long_timeout(),
    )
    result: dict[str, Any] = {
        "node": ref.node,
        "vmid": ref.vmid,
        "guest_type": ref.guest_type,
        "upid": upid,
    }

    if wait_for_completion and isinstance(upid, str):
        result["task"] = await wait_for_task(client, ref.node, upid)

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_shutdown_guest", result, duration_ms=duration_ms)


@write_tool_handler(
    "pve_stopall_guests",
    mutating=True,
    audit_fields=("node",),
)
async def pve_stopall_guests_impl(
    node: str,
    confirm: bool,
    timeout: int = 120,
    wait_for_completion: bool = False,
) -> str:
    """Stop all guests on a node; pair Ceph noout manually per runbook_ref."""
    require_confirm(confirm)
    validate_node_name(node)

    started = time.perf_counter()
    client = get_client()
    upid = await client.post(
        f"/nodes/{node}/stopall",
        data={"timeout": timeout},
        timeout=PveClient.long_timeout(),
    )
    result: dict[str, Any] = {"node": node, "upid": upid}

    if wait_for_completion and isinstance(upid, str):
        result["task"] = await wait_for_task(client, node, upid)

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_stopall_guests", result, duration_ms=duration_ms)
