"""NFS share MCP tool implementations."""

from __future__ import annotations

import time
from typing import Any

from truenas_mcp.constants import NFS4_STALE_STATES
from truenas_mcp.context import get_client, get_settings
from truenas_mcp.tools.helpers import normalize_list, redact_sensitive
from truenas_mcp.tools.response import ok_response, tool_handler


def _share_paths(share: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("path", "paths", "mountpoint"):
        value = share.get(key)
        if isinstance(value, str) and value.strip():
            paths.append(value.strip())
        elif isinstance(value, list):
            paths.extend(str(item).strip() for item in value if item)
    return paths


def nfs_lab_warnings(shares: list[dict[str, Any]], *, lab_export: str) -> list[str]:
    warnings: list[str] = []
    if not shares:
        warnings.append("No NFS shares configured on TrueNAS")
        return warnings

    export_found = False
    for share in shares:
        paths = _share_paths(share)
        if any(lab_export in path or path.endswith(lab_export.rsplit("/", 1)[-1]) for path in paths):
            export_found = True
        if share.get("enabled") is False:
            warnings.append(f"NFS share {share.get('comment') or share.get('id')} is disabled")
    if not export_found:
        warnings.append(f"Lab NFS export path not found among shares (expected path containing {lab_export})")
    return warnings


@tool_handler("truenas_list_nfs_shares")
async def truenas_list_nfs_shares_impl() -> str:
    """List NFS shares; warn when lab HA export path is missing or disabled."""
    started = time.perf_counter()
    settings = get_settings()
    shares = normalize_list(await get_client().call("sharing.nfs.query", [[], {"limit": 50}]))
    warnings = nfs_lab_warnings(shares, lab_export=settings.lab_nfs_export)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "truenas_list_nfs_shares",
        {
            "count": len(shares),
            "lab_nfs_export_hint": settings.lab_nfs_export,
            "shares": redact_sensitive(shares),
        },
        duration_ms=duration_ms,
        warnings=warnings,
    )


def _strip_address(raw: Any) -> str | None:
    """Return the bare IP from ``"1.2.3.4:780"``, ``[fe80::1]:780``, or ``1.2.3.4``."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip().strip('"')
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def _client_ip(entry: dict[str, Any]) -> str | None:
    info = entry.get("info") if isinstance(entry.get("info"), dict) else {}
    for raw in (entry.get("ip"), entry.get("address"), info.get("address"), info.get("callback address")):
        ip = _strip_address(raw)
        if ip:
            return ip
    return None


def normalize_nfs_clients(
    nfs3: list[dict[str, Any]],
    nfs4: list[dict[str, Any]],
    node_by_ip: dict[str, str],
) -> list[dict[str, Any]]:
    """Flatten NFSv3/v4 client entries into ``{ip, node, nfs_version, status, stale, export}``."""
    clients: list[dict[str, Any]] = []
    for entry in nfs3:
        ip = _client_ip(entry)
        clients.append(
            {
                "ip": ip,
                "node": node_by_ip.get(ip or ""),
                "nfs_version": 3,
                "status": None,
                "stale": False,
                "export": entry.get("export") or entry.get("path"),
            }
        )
    for entry in nfs4:
        info = entry.get("info") if isinstance(entry.get("info"), dict) else {}
        ip = _client_ip(entry)
        status = str(info.get("status") or entry.get("status") or "").strip('"') or None
        minor = info.get("minor version")
        clients.append(
            {
                "ip": ip,
                "node": node_by_ip.get(ip or ""),
                "nfs_version": f"4.{minor}" if minor is not None else 4,
                "status": status,
                "stale": (status or "").lower() in NFS4_STALE_STATES,
                "export": entry.get("export"),
                "name": str(info.get("name") or "").strip('"') or None,
            }
        )
    return clients


@tool_handler("truenas_list_nfs_clients")
async def truenas_list_nfs_clients_impl() -> str:
    """Connected NFS clients (v3 + v4), mapped to PVE node names; stale v4 leases flagged."""
    started = time.perf_counter()
    warnings: list[str] = []
    data = await collect_nfs_clients(get_client(), get_settings(), warnings)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("truenas_list_nfs_clients", data, duration_ms=duration_ms, warnings=warnings)


async def collect_nfs_clients(client: Any, settings: Any, warnings: list[str]) -> dict[str, Any]:
    """Query v3 + v4 NFS clients and summarize active/stale/unknown entries."""
    sources: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    for method in ("nfs.get_nfs3_clients", "nfs.get_nfs4_clients"):
        try:
            sources[method] = normalize_list(await client.call(method, []))
        except Exception as exc:
            sources[method] = []
            errors.append(f"{method}: {exc}")
    if len(errors) == len(sources):
        raise RuntimeError("Could not list NFS clients: " + "; ".join(errors))
    warnings.extend(errors)

    node_by_ip = settings.pve_node_by_ip
    clients = normalize_nfs_clients(sources["nfs.get_nfs3_clients"], sources["nfs.get_nfs4_clients"], node_by_ip)
    active = [c for c in clients if not c["stale"]]
    unknown_ips = sorted({c["ip"] for c in active if c["ip"] and not c["node"]})
    if unknown_ips:
        warnings.append("Active NFS clients outside the PVE node map: " + ", ".join(unknown_ips))
    stale = [c for c in clients if c["stale"]]
    if stale:
        warnings.append(f"{len(stale)} stale NFSv4 lease(s) (client gone; expires after the lease time).")

    return {
        "count": len(clients),
        "active_count": len(active),
        "nodes_connected": sorted({c["node"] for c in active if c["node"]}),
        "active_ips": sorted({c["ip"] for c in active if c["ip"]}),
        "unknown_ips": unknown_ips,
        "clients": clients,
        "pve_node_map": node_by_ip,
    }
