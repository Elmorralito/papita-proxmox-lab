"""NFS share MCP tool implementations."""

from __future__ import annotations

import time
from typing import Any

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
