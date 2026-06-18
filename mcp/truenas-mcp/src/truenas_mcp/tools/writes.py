"""Gated write tools for TrueNAS MCP (v2)."""

from __future__ import annotations

import time
from typing import Any

from truenas_mcp.client.jobs import wait_for_job as poll_middleware_job
from truenas_mcp.context import get_client
from truenas_mcp.tools.helpers import parse_model, redact_sensitive, require_confirm
from truenas_mcp.tools.response import ok_response, write_tool_handler
from truenas_mcp.tools.schemas import CreateDatasetInput, DismissAlertInput, UpdateNfsShareInput


@write_tool_handler("truenas_create_dataset", audit_fields=("pool", "name"))
async def truenas_create_dataset_impl(
    pool: str,
    name: str,
    *,
    confirm: bool,
    dataset_type: str = "FILESYSTEM",
    wait_for_job: bool = True,
    job_timeout_sec: float = 120.0,
) -> str:
    """Create a ZFS dataset under a pool (requires confirm=true)."""
    started = time.perf_counter()
    parsed = parse_model(CreateDatasetInput, pool=pool, name=name, confirm=confirm, dataset_type=dataset_type)
    require_confirm(parsed.confirm)
    dataset_name = f"{parsed.pool}/{parsed.name}" if "/" not in parsed.name else parsed.name
    client = get_client()
    result = await client.call(
        "pool.dataset.create",
        [{"name": dataset_name, "type": parsed.dataset_type}],
    )
    job_id = result if isinstance(result, int) else None
    job: dict[str, Any] | None = None
    if wait_for_job and job_id is not None:
        job = await poll_middleware_job(client, job_id, timeout_sec=job_timeout_sec)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "truenas_create_dataset",
        {"dataset": dataset_name, "job_id": job_id, "job": redact_sensitive(job)},
        duration_ms=duration_ms,
    )


@write_tool_handler("truenas_update_nfs_share", audit_fields=("share_id",))
async def truenas_update_nfs_share_impl(
    share_id: int,
    *,
    confirm: bool,
    enabled: bool | None = None,
    comment: str | None = None,
    wait_for_job: bool = True,
    job_timeout_sec: float = 120.0,
) -> str:
    """Update an NFS share by id (requires confirm=true)."""
    started = time.perf_counter()
    parsed = parse_model(
        UpdateNfsShareInput,
        share_id=share_id,
        confirm=confirm,
        enabled=enabled,
        comment=comment,
    )
    require_confirm(parsed.confirm)
    update_data: dict[str, Any] = {"id": parsed.share_id}
    if parsed.enabled is not None:
        update_data["enabled"] = parsed.enabled
    if parsed.comment is not None:
        update_data["comment"] = parsed.comment
    client = get_client()
    result = await client.call("sharing.nfs.update", [update_data])
    job_id = result if isinstance(result, int) else None
    job: dict[str, Any] | None = None
    if wait_for_job and job_id is not None:
        job = await poll_middleware_job(client, job_id, timeout_sec=job_timeout_sec)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "truenas_update_nfs_share",
        {"share_id": parsed.share_id, "job_id": job_id, "job": redact_sensitive(job)},
        duration_ms=duration_ms,
    )


@write_tool_handler("truenas_dismiss_alert", audit_fields=("alert_id",))
async def truenas_dismiss_alert_impl(alert_id: str, *, confirm: bool) -> str:
    """Dismiss an active alert (requires confirm=true)."""
    started = time.perf_counter()
    parsed = parse_model(DismissAlertInput, alert_id=alert_id, confirm=confirm)
    require_confirm(parsed.confirm)
    await get_client().call("alert.dismiss", [parsed.alert_id])
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "truenas_dismiss_alert",
        {"alert_id": parsed.alert_id, "dismissed": True},
        duration_ms=duration_ms,
    )
