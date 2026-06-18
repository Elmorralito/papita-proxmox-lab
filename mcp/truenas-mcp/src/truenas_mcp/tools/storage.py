"""Storage MCP tool implementations."""

from __future__ import annotations

import time

from truenas_mcp.context import get_client
from truenas_mcp.tools.helpers import (
    dataset_capacity_warnings,
    normalize_list,
    pool_health_warnings,
    redact_sensitive,
)
from truenas_mcp.tools.response import ok_response, tool_handler


@tool_handler("truenas_list_pools")
async def truenas_list_pools_impl() -> str:
    """List ZFS pools with health status and capacity."""
    started = time.perf_counter()
    pools = normalize_list(await get_client().call("pool.query"))
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "truenas_list_pools",
        {"count": len(pools), "pools": redact_sensitive(pools)},
        duration_ms=duration_ms,
        warnings=pool_health_warnings(pools),
    )


@tool_handler("truenas_list_datasets")
async def truenas_list_datasets_impl(limit: int = 50) -> str:
    """List ZFS datasets with mount points and space utilization."""
    started = time.perf_counter()
    bounded = max(1, min(limit, 200))
    datasets = normalize_list(await get_client().call("pool.dataset.query"))
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "truenas_list_datasets",
        {"count": len(datasets), "datasets": redact_sensitive(datasets[:bounded])},
        duration_ms=duration_ms,
        warnings=dataset_capacity_warnings(datasets),
    )


@tool_handler("truenas_list_scrub_tasks")
async def truenas_list_scrub_tasks_impl(limit: int = 20) -> str:
    """List configured pool scrub tasks and schedules."""
    started = time.perf_counter()
    bounded = max(1, min(limit, 100))
    scrubs = normalize_list(await get_client().call("pool.scrub.query", [[], {"limit": bounded}]))
    duration_ms = int((time.perf_counter() - started) * 1000)
    warnings: list[str] = []
    if not scrubs:
        warnings.append("No pool scrub tasks configured")
    return ok_response(
        "truenas_list_scrub_tasks",
        {"count": len(scrubs), "scrub_tasks": redact_sensitive(scrubs[:bounded])},
        duration_ms=duration_ms,
        warnings=warnings,
    )


@tool_handler("truenas_list_disks")
async def truenas_list_disks_impl() -> str:
    """List physical disks and temperature alert state."""
    started = time.perf_counter()
    client = get_client()
    disks = normalize_list(await client.call("disk.query"))
    temp_alerts = await client.call("disk.temperature_alerts")
    duration_ms = int((time.perf_counter() - started) * 1000)
    warnings: list[str] = []
    if isinstance(temp_alerts, list) and temp_alerts:
        warnings.append(f"{len(temp_alerts)} disk(s) over temperature threshold")
    return ok_response(
        "truenas_list_disks",
        {
            "count": len(disks),
            "disks": redact_sensitive(disks),
            "temperature_alerts": redact_sensitive(temp_alerts),
        },
        duration_ms=duration_ms,
        warnings=warnings,
    )
