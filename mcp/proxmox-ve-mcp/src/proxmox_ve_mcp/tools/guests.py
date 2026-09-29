"""Guest config and mutating MCP tools."""

import time
from typing import Any

from proxmox_ve_mcp.client.http import PveClient
from proxmox_ve_mcp.client.tasks import wait_for_task
from proxmox_ve_mcp.constants import MAX_WAIT_CALL_SEC, TASK_WAIT_MARGIN_SEC
from proxmox_ve_mcp.context import get_client, get_settings
from proxmox_ve_mcp.tools.ha import ha_placement, ha_stop_warning
from proxmox_ve_mcp.tools.helpers import parse_model, redact_config, require_confirm
from proxmox_ve_mcp.tools.response import ok_response, tool_handler, write_tool_handler
from proxmox_ve_mcp.tools.schemas import GuestRefInput, validate_node_name


async def _wait_or_pending(client: Any, node: str, upid: str, timeout_sec: float, warnings: list[str]) -> dict:
    """Wait for *upid*; a timeout is not a failure (the action was submitted)."""
    try:
        return await wait_for_task(client, node, upid, timeout_sec=timeout_sec)
    except TimeoutError:
        warnings.append(f"Task still running after {timeout_sec:.0f}s; poll it with pve_wait_for_task(upid).")
        return {"upid": upid, "finished": False}


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
    warnings: list[str] = []
    upid = await client.post(f"/nodes/{ref.node}/{ref.guest_type}/{ref.vmid}/status/start")
    result: dict[str, Any] = {
        "node": ref.node,
        "vmid": ref.vmid,
        "guest_type": ref.guest_type,
        "upid": upid,
    }

    if wait_for_completion and isinstance(upid, str):
        result["task"] = await _wait_or_pending(client, ref.node, upid, MAX_WAIT_CALL_SEC, warnings)

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_start_guest", result, duration_ms=duration_ms, warnings=warnings)


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
    warnings: list[str] = []
    await ha_stop_warning(client, ref.vmid, ref.guest_type, warnings)
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
        result["task"] = await _wait_or_pending(client, ref.node, upid, timeout + TASK_WAIT_MARGIN_SEC, warnings)

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_shutdown_guest", result, duration_ms=duration_ms, warnings=warnings)


@write_tool_handler(
    "pve_stop_guest",
    mutating=True,
    audit_fields=("node", "vmid", "guest_type", "reason", "overrule_shutdown"),
)
async def pve_stop_guest_impl(  # pylint: disable=too-many-arguments
    node: str,
    vmid: int,
    guest_type: str,
    confirm: bool,
    reason: str,
    overrule_shutdown: bool = False,
    wait_for_completion: bool = False,
) -> str:
    """Hard stop (power off) a VM or CT; unsaved guest state is lost."""
    require_confirm(confirm)
    ref = parse_model(GuestRefInput, node=node, vmid=vmid, guest_type=guest_type)
    assert isinstance(ref, GuestRefInput)
    if len(reason.strip()) < 3:
        raise ValueError("reason is required (min 3 characters) for a hard stop")

    started = time.perf_counter()
    client = get_client()
    warnings = [f"Hard stop of {ref.guest_type}/{ref.vmid}: equivalent to pulling power; unsaved state is lost."]
    if ref.vmid in get_settings().infra_vmids:
        warnings.append(f"VMID {ref.vmid} is a lab infrastructure guest (LAN router): TrueNAS becomes unreachable.")
    await ha_stop_warning(client, ref.vmid, ref.guest_type, warnings)

    data = {"overrule-shutdown": 1} if overrule_shutdown else None
    upid = await client.post(f"/nodes/{ref.node}/{ref.guest_type}/{ref.vmid}/status/stop", data=data)
    result: dict[str, Any] = {
        "node": ref.node,
        "vmid": ref.vmid,
        "guest_type": ref.guest_type,
        "reason": reason.strip(),
        "upid": upid,
    }

    if wait_for_completion and isinstance(upid, str):
        result["task"] = await _wait_or_pending(client, ref.node, upid, TASK_WAIT_MARGIN_SEC * 2, warnings)

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_stop_guest", result, duration_ms=duration_ms, warnings=warnings)


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
    warnings: list[str] = []
    placement = await ha_placement(client, warnings)
    ha_here = sorted(v for v, n in placement.vmid_nodes.items() if n == node) if placement else []
    if ha_here:
        warnings.append(
            f"HA-managed guest(s) {ha_here} on {node}: stopall may route them through HA and set their "
            + "requested state to 'stopped'; check pve_get_ha_status and restart them with pve_start_guest."
        )
    upid = await client.post(
        f"/nodes/{node}/stopall",
        data={"timeout": timeout},
        timeout=PveClient.long_timeout(),
    )
    result: dict[str, Any] = {"node": node, "upid": upid}

    if wait_for_completion and isinstance(upid, str):
        result["task"] = await _wait_or_pending(client, node, upid, timeout + TASK_WAIT_MARGIN_SEC, warnings)

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_stopall_guests", result, duration_ms=duration_ms, warnings=warnings)
