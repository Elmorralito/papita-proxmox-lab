"""Token diagnostics and node address discovery tools."""

from __future__ import annotations

import time
from typing import Any

from proxmox_ve_mcp.client.errors import PveApiError
from proxmox_ve_mcp.client.permissions import TOKEN_ACL_HINT
from proxmox_ve_mcp.context import get_client, get_settings
from proxmox_ve_mcp.tools.helpers import normalize_list
from proxmox_ve_mcp.tools.response import ok_response, tool_handler

# Endpoints probed by pve_check_token (name, path template, required privilege hint)
_TOKEN_PROBES: tuple[tuple[str, str, str | None], ...] = (
    ("version", "/version", None),
    ("permissions", "/access/permissions", None),
    ("cluster_resources", "/cluster/resources", "Sys.Audit on /"),
    ("cluster_config_nodes", "/cluster/config/nodes", "Sys.Audit on /"),
)


@tool_handler("pve_check_token")
async def pve_check_token_impl() -> str:
    """Validate API token auth and report which MCP endpoints are allowed."""
    started = time.perf_counter()
    client = get_client()
    settings = get_settings()
    warnings: list[str] = []
    probes: list[dict[str, Any]] = []

    sample_node: str | None = None

    for name, path, privilege_hint in _TOKEN_PROBES:
        entry: dict[str, Any] = {"name": name, "path": path, "ok": False}
        try:
            data = await client.get(path, params={"type": "node"} if name == "cluster_resources" else None)
            entry["ok"] = True
            if name == "permissions":
                entry["permissions"] = data
            elif name == "cluster_resources":
                nodes = normalize_list(data)
                entry["node_count"] = len(nodes)
                if nodes:
                    sample_node = str(nodes[0].get("node", "")) or None
            elif name == "cluster_config_nodes":
                entry["node_count"] = len(normalize_list(data))
        except PveApiError as exc:
            entry["error"] = exc.to_dict()
            if privilege_hint:
                entry["required"] = privilege_hint
        probes.append(entry)

    if sample_node:
        network_path = f"/nodes/{sample_node}/network"
        iface_path = f"/nodes/{sample_node}/network/nic0"
        for name, path in (
            ("node_network_list", network_path),
            ("node_network_detail", iface_path),
        ):
            entry = {"name": name, "path": path, "ok": False, "sample_node": sample_node}
            try:
                data = await client.get(path)
                entry["ok"] = True
                if name == "node_network_list":
                    entry["iface_count"] = len(normalize_list(data))
            except PveApiError as exc:
                entry["error"] = exc.to_dict()
                entry["required"] = f"Sys.Audit on /nodes/{sample_node}"
            probes.append(entry)

    failed = [p for p in probes if not p.get("ok")]
    if failed and all(p["name"] in {"version", "permissions"} for p in failed):
        warnings.append("Token authenticates but has no useful read permissions.")
    elif failed:
        warnings.append(
            "Some endpoints returned 403. Assign Sys.Audit (or Administrator) to the "
            "API token at path / — not only to the owning user."
        )
        warnings.append(TOKEN_ACL_HINT)

    summary = {
        "api_user": settings.user,
        "token_id": settings.token_id,
        "api_entry_host": settings.host,
        "probes": probes,
        "all_required_ok": not failed,
        "failed_probe_count": len(failed),
    }
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pve_check_token", summary, duration_ms=duration_ms, warnings=warnings)


@tool_handler("pve_list_node_addresses")
async def pve_list_node_addresses_impl() -> str:
    """List cluster node corosync (ring0) and interface addresses when permitted."""
    started = time.perf_counter()
    client = get_client()
    warnings: list[str] = []

    nodes_data = normalize_list(await client.get("/cluster/resources", params={"type": "node"}))
    node_names = sorted(name for item in nodes_data if (name := item.get("node")) is not None)

    ring0_by_node: dict[str, str | None] = {}
    try:
        config_nodes = normalize_list(await client.get("/cluster/config/nodes"))
        for entry in config_nodes:
            node_name = entry.get("name") or entry.get("node")
            if node_name:
                ring0_by_node[str(node_name)] = entry.get("ring0_addr")
    except PveApiError as exc:
        warnings.append(f"ring0_addr unavailable: {exc.to_dict().get('hint', exc)}")

    addresses: list[dict[str, Any]] = []
    for node in node_names:
        node_entry: dict[str, Any] = {
            "node": node,
            "status": next(
                (item.get("status") for item in nodes_data if item.get("node") == node),
                None,
            ),
            "ring0_addr": ring0_by_node.get(node),
            "interfaces": [],
        }
        try:
            interfaces = normalize_list(await client.get(f"/nodes/{node}/network"))
            for iface in interfaces:
                iface_name = iface.get("iface")
                if not iface_name:
                    continue
                try:
                    detail = await client.get(f"/nodes/{node}/network/{iface_name}")
                    address = detail.get("address") or detail.get("cidr")
                    if not address:
                        continue
                    node_entry["interfaces"].append(
                        {
                            "iface": iface_name,
                            "address": address,
                            "gateway": detail.get("gateway"),
                            "active": detail.get("active", iface.get("active")),
                            "type": detail.get("type", iface.get("type")),
                        }
                    )
                except PveApiError:
                    continue
        except PveApiError as exc:
            warnings.append(f"{node}: network list denied — {exc.to_dict().get('hint', exc)}")
        addresses.append(node_entry)

    has_ring0 = any(entry.get("ring0_addr") for entry in addresses)
    has_iface = any(entry.get("interfaces") for entry in addresses)
    if not has_ring0 and not has_iface:
        warnings.append(TOKEN_ACL_HINT)

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pve_list_node_addresses",
        {"nodes": addresses, "count": len(addresses)},
        duration_ms=duration_ms,
        warnings=warnings,
    )
