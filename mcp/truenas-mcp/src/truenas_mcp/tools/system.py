"""System and health MCP tool implementations."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from truenas_mcp.client.errors import TnasApiError
from truenas_mcp.constants import LAB_CLUSTER_NAME, LAB_TRUENAS_HOST
from truenas_mcp.context import get_client, get_settings
from truenas_mcp.tools.helpers import critical_alerts, normalize_list, pool_health_warnings, redact_sensitive
from truenas_mcp.tools.monitoring import _scrutiny_warnings
from truenas_mcp.tools.response import ok_response, tool_handler
from truenas_mcp.tools.sharing import nfs_lab_warnings


@tool_handler("truenas_get_system_info")
async def truenas_get_system_info_impl() -> str:
    """Return TrueNAS hostname, version, uptime, and middleware state."""
    started = time.perf_counter()
    client = get_client()
    info, state = await asyncio.gather(
        client.call("system.info"),
        client.call("system.state"),
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "truenas_get_system_info",
        redact_sensitive({"info": info, "state": state}),
        duration_ms=duration_ms,
    )


@tool_handler("truenas_list_alerts")
async def truenas_list_alerts_impl() -> str:
    """List active TrueNAS alerts (hardware, pool, config issues)."""
    started = time.perf_counter()
    alerts = normalize_list(await get_client().call("alert.list"))
    warnings: list[str] = []
    critical = critical_alerts(alerts)
    if critical:
        warnings.append(f"{len(critical)} active WARNING/CRITICAL alert(s)")
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "truenas_list_alerts",
        {"count": len(alerts), "alerts": redact_sensitive(alerts)},
        duration_ms=duration_ms,
        warnings=warnings,
    )


@tool_handler("truenas_list_jobs")
async def truenas_list_jobs_impl(limit: int = 20) -> str:
    """List recent middleware jobs (scrubs, replication, updates)."""
    started = time.perf_counter()
    bounded = max(1, min(limit, 100))
    jobs = normalize_list(await get_client().call("core.get_jobs"))
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "truenas_list_jobs",
        {"count": len(jobs), "jobs": redact_sensitive(jobs[:bounded])},
        duration_ms=duration_ms,
    )


def _error_message(exc: BaseException) -> str:
    if isinstance(exc, TnasApiError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


@tool_handler("truenas_system_summary")
async def truenas_system_summary_impl() -> str:
    """Operator dashboard: system info, alerts, pools, datasets, jobs."""
    started = time.perf_counter()
    client = get_client()
    settings = get_settings()
    warnings: list[str] = []

    results = await asyncio.gather(
        client.call("system.info"),
        client.call("system.state"),
        client.call("alert.list"),
        client.call("pool.query"),
        client.call("pool.dataset.query"),
        client.call("core.get_jobs"),
        client.call("sharing.nfs.query", [[], {"limit": 50}]),
        client.call("pool.scrub.query", [[], {"limit": 20}]),
        client.call("app.query", [[], {"limit": 50}]),
        return_exceptions=True,
    )

    summary: dict[str, Any] = {
        "truenas_host": settings.host,
        "lab_truenas_host": LAB_TRUENAS_HOST,
        "lab_nfs_export_hint": settings.lab_nfs_export,
        "lab_ha_pool_name": settings.lab_ha_pool_name,
        "uptime_kuma_hint": f"Uptime Kuma on Proxmox cluster {LAB_CLUSTER_NAME}",
    }

    info_res, state_res, alerts_res, pools_res, datasets_res, jobs_res, nfs_res, scrub_res, apps_res = results

    if isinstance(info_res, Exception):
        warnings.append(f"system.info: {_error_message(info_res)}")
        summary["system"] = None
    else:
        summary["system"] = redact_sensitive(info_res)

    if isinstance(state_res, Exception):
        warnings.append(f"system.state: {_error_message(state_res)}")
        summary["state"] = None
    else:
        summary["state"] = state_res
        if state_res not in (None, "READY", "ready"):
            warnings.append(f"System state is {state_res!r} (expected READY)")

    alerts: list[dict[str, Any]] = []
    if isinstance(alerts_res, Exception):
        warnings.append(f"alert.list: {_error_message(alerts_res)}")
    else:
        alerts = normalize_list(alerts_res)
        summary["alerts"] = {"count": len(alerts), "critical": len(critical_alerts(alerts))}
        if critical_alerts(alerts):
            warnings.append("Active WARNING/CRITICAL alerts require attention")

    pools: list[dict[str, Any]] = []
    if isinstance(pools_res, Exception):
        warnings.append(f"pool.query: {_error_message(pools_res)}")
    else:
        pools = normalize_list(pools_res)
        summary["pools"] = {
            "count": len(pools),
            "items": [{"name": p.get("name"), "status": p.get("status")} for p in pools[:10]],
        }
        warnings.extend(pool_health_warnings(pools))

    if isinstance(datasets_res, Exception):
        warnings.append(f"pool.dataset.query: {_error_message(datasets_res)}")
    else:
        datasets = normalize_list(datasets_res)
        summary["datasets"] = {"count": len(datasets)}
        for ds in datasets:
            mountpoint = str(ds.get("mountpoint", ""))
            if mountpoint and settings.lab_nfs_export in mountpoint:
                summary["lab_nfs_dataset"] = {
                    "name": ds.get("name"),
                    "mountpoint": mountpoint,
                }
                break

    if isinstance(jobs_res, Exception):
        warnings.append(f"core.get_jobs: {_error_message(jobs_res)}")
    else:
        jobs = normalize_list(jobs_res)
        failed = [j for j in jobs if str(j.get("state", "")).upper() == "FAILED"]
        summary["jobs"] = {"count": len(jobs), "failed_recent": len(failed)}
        if failed:
            warnings.append(f"{len(failed)} recent job(s) in FAILED state")

    if isinstance(nfs_res, Exception):
        warnings.append(f"sharing.nfs.query: {_error_message(nfs_res)}")
    else:
        nfs_shares = normalize_list(nfs_res)
        summary["nfs_shares"] = {"count": len(nfs_shares)}
        warnings.extend(nfs_lab_warnings(nfs_shares, lab_export=settings.lab_nfs_export))

    if isinstance(scrub_res, Exception):
        warnings.append(f"pool.scrub.query: {_error_message(scrub_res)}")
    else:
        scrubs = normalize_list(scrub_res)
        summary["scrub_tasks"] = {"count": len(scrubs)}
        if not scrubs:
            warnings.append("No pool scrub tasks configured")

    if isinstance(apps_res, Exception):
        warnings.append(f"app.query: {_error_message(apps_res)}")
    else:
        apps = normalize_list(apps_res)
        summary["apps"] = {
            "count": len(apps),
            "items": [{"name": a.get("name"), "state": a.get("state")} for a in apps[:10]],
        }
        warnings.extend(_scrutiny_warnings(apps, settings.lab_scrutiny_app_name))

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "truenas_system_summary",
        summary,
        duration_ms=duration_ms,
        warnings=warnings,
        meta_extra={
            "proxmox_hint": "Use proxmox-ve MCP for HA/NFS on PVE; Uptime Kuma on pvecm-oldtimers",
        },
    )
