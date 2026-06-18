"""Monitoring, SMART, reporting, and app inventory tools."""

from __future__ import annotations

import time
from typing import Any

from truenas_mcp.constants import LAB_CLUSTER_NAME
from truenas_mcp.context import get_client, get_settings
from truenas_mcp.tools.helpers import normalize_list, redact_sensitive
from truenas_mcp.tools.response import ok_response, tool_handler
from truenas_mcp.tools.schemas import ReportingDataInput, query_options


@tool_handler("truenas_check_api_key")
async def truenas_check_api_key_impl() -> str:
    """Validate API key by calling system.state and returning session metadata."""
    started = time.perf_counter()
    settings = get_settings()
    client = get_client()
    state = await client.call("system.state")
    info = await client.call("system.info")
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "truenas_check_api_key",
        {
            "authenticated": True,
            "host": settings.host,
            "ws_uri": settings.ws_uri,
            "state": state,
            "version": info.get("version") if isinstance(info, dict) else None,
        },
        duration_ms=duration_ms,
    )


@tool_handler("truenas_list_smart_results")
async def truenas_list_smart_results_impl(limit: int = 20) -> str:
    """List SMART self-test results (complements Scrutiny app on NAS)."""
    started = time.perf_counter()
    bounded = max(1, min(limit, 100))
    results = await get_client().call("smart.test.results")
    items = results if isinstance(results, list) else normalize_list(results)
    duration_ms = int((time.perf_counter() - started) * 1000)
    warnings: list[str] = []
    for item in items[:bounded]:
        if not isinstance(item, dict):
            continue
        for test in item.get("tests", []) if isinstance(item.get("tests"), list) else []:
            if str(test.get("status", "")).upper() not in {"SUCCESS", "PASSED"}:
                warnings.append("SMART test non-success on disk entry")
                break
    return ok_response(
        "truenas_list_smart_results",
        {"count": len(items), "results": redact_sensitive(items[:bounded])},
        duration_ms=duration_ms,
        warnings=warnings,
    )


@tool_handler("truenas_list_alert_policies")
async def truenas_list_alert_policies_impl() -> str:
    """List configured alert policies (IMMEDIATELY, HOURLY, etc.)."""
    started = time.perf_counter()
    policies = await get_client().call("alert.list_policies")
    duration_ms = int((time.perf_counter() - started) * 1000)
    if isinstance(policies, list):
        payload = {"count": len(policies), "policies": policies}
    else:
        payload = {"policies": policies}
    return ok_response("truenas_list_alert_policies", payload, duration_ms=duration_ms)


@tool_handler("truenas_get_reporting_data")
async def truenas_get_reporting_data_impl(
    graph: str = "cpu",
    identifier: str | None = None,
    start: int | None = None,
    end: int | None = None,
    unit: str | None = "HOUR",
    page: int = 1,
    aggregate: bool = True,
) -> str:
    """Fetch reporting graph data (cpu, memory, disk, load, etc.)."""
    started = time.perf_counter()
    params = ReportingDataInput(
        graph=graph,  # type: ignore[arg-type]
        identifier=identifier,
        start=start,
        end=end,
        unit=unit,  # type: ignore[arg-type]
        page=page,
        aggregate=aggregate,
    )
    graph_obj: dict[str, Any] = {"name": params.graph}
    if params.identifier:
        graph_obj["identifier"] = params.identifier

    if params.start is not None and params.end is not None:
        query: dict[str, Any] = {"start": params.start, "end": params.end, "aggregate": params.aggregate}
    else:
        query = {"unit": params.unit, "page": params.page, "aggregate": params.aggregate}

    data = await get_client().call("reporting.get_data", [[graph_obj], query])
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "truenas_get_reporting_data",
        {"graph": graph_obj, "query": query, "data": redact_sensitive(data)},
        duration_ms=duration_ms,
    )


def _scrutiny_warnings(apps: list[dict[str, Any]], scrutiny_name: str) -> list[str]:
    warnings: list[str] = []
    scrutiny = next((app for app in apps if app.get("name") == scrutiny_name or app.get("id") == scrutiny_name), None)
    if scrutiny is None:
        warnings.append(f"Scrutiny app {scrutiny_name!r} not installed")
    elif str(scrutiny.get("state", "")).upper() != "RUNNING":
        warnings.append(f"Scrutiny app state is {scrutiny.get('state')!r} (expected RUNNING)")
    return warnings


@tool_handler("truenas_list_apps")
async def truenas_list_apps_impl(limit: int = 50) -> str:
    """List TrueNAS apps (Scrutiny, Tailscale, etc.) with run state."""
    started = time.perf_counter()
    settings = get_settings()
    bounded = max(1, min(limit, 100))
    apps = normalize_list(await get_client().call("app.query", [[], query_options(limit=bounded)]))
    duration_ms = int((time.perf_counter() - started) * 1000)
    warnings = _scrutiny_warnings(apps, settings.lab_scrutiny_app_name)
    summary = [
        {
            "name": app.get("name"),
            "id": app.get("id"),
            "state": app.get("state"),
            "upgrade_available": app.get("upgrade_available"),
        }
        for app in apps
    ]
    uptime_hint = (
        f"Uptime Kuma runs on Proxmox cluster {LAB_CLUSTER_NAME} — " "use proxmox-ve MCP / papita_uptime_kuma_bootstrap"
    )
    return ok_response(
        "truenas_list_apps",
        {
            "count": len(apps),
            "apps": summary,
            "lab_scrutiny_app": settings.lab_scrutiny_app_name,
            "uptime_kuma_hint": uptime_hint,
        },
        duration_ms=duration_ms,
        warnings=warnings,
        meta_extra={"proxmox_hint": "Cluster monitoring via Uptime Kuma on PVE, not TrueNAS app"},
    )
