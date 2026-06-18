"""TrueNAS middleware job polling helpers."""

from __future__ import annotations

import asyncio
from typing import Any

from truenas_mcp.client.errors import TnasApiError
from truenas_mcp.client.websocket import TnasClient


async def wait_for_job(
    client: TnasClient,
    job_id: int,
    *,
    timeout_sec: float = 120.0,
    poll_interval_sec: float = 2.0,
) -> dict[str, Any]:
    """Poll ``core.get_jobs`` until *job_id* reaches a terminal state."""
    deadline = asyncio.get_running_loop().time() + timeout_sec
    last: dict[str, Any] = {}

    while asyncio.get_running_loop().time() < deadline:
        raw = await client.call("core.get_jobs")
        jobs = raw if isinstance(raw, list) else []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            if job.get("id") == job_id:
                last = job
                state = str(job.get("state", "")).upper()
                if state in {"SUCCESS", "FAILED", "ABORTED", "ERROR"}:
                    if state != "SUCCESS":
                        raise TnasApiError(
                            f"Job {job_id} finished with state {state}",
                            code="JOB_FAILED",
                            details=job,
                        )
                    return job
        await asyncio.sleep(poll_interval_sec)

    raise TimeoutError(f"Job {job_id} did not finish within {timeout_sec}s; last={last.get('state')}")
