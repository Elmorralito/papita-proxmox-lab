"""Storage MCP tool implementations."""

import time
from typing import Any

from proxmox_ve_mcp.client.errors import PveApiError
from proxmox_ve_mcp.context import get_client
from proxmox_ve_mcp.tools.helpers import normalize_list, parse_model
from proxmox_ve_mcp.tools.response import ok_response, tool_handler
from proxmox_ve_mcp.tools.schemas import ListStorageInput


@tool_handler("pve_list_storage")
async def pve_list_storage_impl(node: str | None = None) -> str:
    """List storage definitions and optional per-node usage.

    Maps to pvesm status read path in docs/TIPSNTRICKS.md.
    """
    started = time.perf_counter()
    client = get_client()
    warnings: list[str] = []

    parsed = parse_model(ListStorageInput, node=node)
    assert isinstance(parsed, ListStorageInput)

    definitions = normalize_list(await client.get("/storage"))
    node_status: list[dict[str, Any]] = []

    if parsed.node:
        try:
            node_storages = normalize_list(await client.get(f"/nodes/{parsed.node}/storage"))
            for storage in node_storages:
                storage_id = storage.get("storage")
                if not storage_id:
                    continue
                try:
                    status = await client.get(f"/nodes/{parsed.node}/storage/{storage_id}/status")
                    node_status.append(
                        {
                            "node": parsed.node,
                            "storage": storage_id,
                            "status": status,
                            "enabled": storage.get("enabled"),
                            "content": storage.get("content"),
                        }
                    )
                except PveApiError as exc:
                    warnings.append(f"Status for {storage_id} on {parsed.node}: {exc}")
        except PveApiError as exc:
            warnings.append(f"Could not list storage on node {parsed.node}: {exc}")

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pve_list_storage",
        {
            "definitions": definitions,
            "node_status": node_status,
            "definition_count": len(definitions),
        },
        duration_ms=duration_ms,
        warnings=warnings,
    )
