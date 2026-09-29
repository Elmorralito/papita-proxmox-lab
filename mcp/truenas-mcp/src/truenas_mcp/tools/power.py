"""Guarded TrueNAS shutdown/reboot tools (destructive)."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from truenas_mcp.client.errors import TnasApiError
from truenas_mcp.context import get_client, get_settings
from truenas_mcp.tools.helpers import normalize_list, parse_model, require_confirm
from truenas_mcp.tools.response import ok_response, write_tool_handler
from truenas_mcp.tools.schemas import PowerInput
from truenas_mcp.tools.sharing import collect_nfs_clients

BLOCKING_JOB_KEYWORDS = ("scrub", "replication", "resilver", "update")
_SIGNATURE_ERROR_HINTS = ("argument", "parameter", "positional", "too many")


async def _blocking_jobs(client: Any) -> list[dict[str, Any]]:
    """Running middleware jobs that must not be interrupted (scrub, replication, update)."""
    jobs = normalize_list(await client.call("core.get_jobs", [[["state", "=", "RUNNING"]]]))
    return [
        {"id": job.get("id"), "method": job.get("method"), "progress": (job.get("progress") or {}).get("percent")}
        for job in jobs
        if any(key in str(job.get("method", "")).lower() for key in BLOCKING_JOB_KEYWORDS)
    ]


async def _submit(client: Any, method: str, reason: str, delay_s: int, warnings: list[str]) -> Any:
    """Call ``system.shutdown|reboot`` (24.10+ ``reason`` form, falling back to the older options-only form)."""
    try:
        return await client.call(method, [reason, {"delay": delay_s}])
    except TnasApiError as exc:
        if exc.code != "TRUENAS_API_ERROR" or not any(h in str(exc.details).lower() for h in _SIGNATURE_ERROR_HINTS):
            raise
    warnings.append(f"{method} rejected the reason argument (pre-24.10 SCALE); retried without it.")
    return await client.call(method, [{"delay": delay_s}])


async def _power(  # noqa: C901
    tool: str,
    method: str,
    *,
    reason: str,
    confirm: bool,
    delay_s: int,
    force: bool,
    expected_clients: list[str] | None,
    plan_only: bool,
) -> str:
    if not plan_only:
        require_confirm(confirm)
    parsed = parse_model(
        PowerInput, reason=reason, delay_s=delay_s, force=force, expected_clients=expected_clients or []
    )
    started = time.perf_counter()
    client = get_client()
    warnings: list[str] = []
    refusals: list[str] = []

    nfs: dict[str, Any] = {}
    unexpected: list[str] = []
    try:
        nfs = await collect_nfs_clients(client, get_settings(), warnings)
        unexpected = sorted(set(nfs["active_ips"]) - set(parsed.expected_clients))
    except Exception as exc:
        refusals.append(f"Could not verify NFS clients ({exc}).")
    if unexpected:
        refusals.append(
            f"Active NFS clients not in expected_clients: {unexpected}; guests on NFS disks hang if the NAS "
            + "disappears. Shut PVE nodes down first (pve_shutdown_node)."
        )

    jobs = await _blocking_jobs(client)
    if jobs:
        refusals.append(f"Running job(s) would be interrupted: {[j['method'] for j in jobs]}.")

    if refusals and parsed.force:
        warnings.extend(f"Overridden by force=true: {r}" for r in refusals)
        refusals = []

    plan: dict[str, Any] = {
        "action": method.removeprefix("system."),
        "reason": parsed.reason,
        "delay_s": parsed.delay_s,
        "expected_clients": parsed.expected_clients,
        "nfs_active_ips": nfs.get("active_ips"),
        "nfs_nodes_connected": nfs.get("nodes_connected"),
        "blocking_jobs": jobs,
        "refusals": refusals,
    }
    if plan_only:
        plan["would_execute"] = not refusals
        duration_ms = int((time.perf_counter() - started) * 1000)
        return ok_response(tool, plan, duration_ms=duration_ms, warnings=warnings)

    if refusals:
        raise TnasApiError(
            f"{method} refused: " + " ".join(refusals),
            code="POWER_GUARD",
            method=method,
            hint="Run with plan_only=true to see every check; force=true overrides (unsafe for NFS guests).",
        )

    connection_dropped = False
    job_id: Any = None
    try:
        job_id = await _submit(client, method, parsed.reason, parsed.delay_s, warnings)
    except TnasApiError as exc:
        if exc.code != "CONNECTION_ERROR":
            raise
        connection_dropped = True
        warnings.append(f"Connection dropped during {method} (expected when delay_s=0); verify the NAS is down.")

    warnings.append("The MCP connection to TrueNAS will drop; later calls fail until the NAS is back.")
    plan.update(
        {
            "submitted": True,
            "job_id": job_id if isinstance(job_id, int) else None,
            "connection_dropped": connection_dropped,
            "power_off_at": (datetime.now(UTC) + timedelta(seconds=parsed.delay_s)).isoformat(timespec="seconds"),
        }
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(tool, plan, duration_ms=duration_ms, warnings=warnings)


@write_tool_handler("truenas_shutdown", audit_fields=("reason", "delay_s", "force", "plan_only"))
async def truenas_shutdown_impl(
    reason: str,
    *,
    confirm: bool = False,
    delay_s: int = 0,
    force: bool = False,
    expected_clients: list[str] | None = None,
    plan_only: bool = False,
) -> str:
    """Power off the NAS after the NFS-client and running-job guards pass."""
    return await _power(
        "truenas_shutdown",
        "system.shutdown",
        reason=reason,
        confirm=confirm,
        delay_s=delay_s,
        force=force,
        expected_clients=expected_clients,
        plan_only=plan_only,
    )


@write_tool_handler("truenas_reboot", audit_fields=("reason", "delay_s", "force", "plan_only"))
async def truenas_reboot_impl(
    reason: str,
    *,
    confirm: bool = False,
    delay_s: int = 0,
    force: bool = False,
    expected_clients: list[str] | None = None,
    plan_only: bool = False,
) -> str:
    """Reboot the NAS after the NFS-client and running-job guards pass."""
    return await _power(
        "truenas_reboot",
        "system.reboot",
        reason=reason,
        confirm=confirm,
        delay_s=delay_s,
        force=force,
        expected_clients=expected_clients,
        plan_only=plan_only,
    )
