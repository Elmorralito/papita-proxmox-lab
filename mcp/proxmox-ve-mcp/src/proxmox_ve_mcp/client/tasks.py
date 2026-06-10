"""Proxmox task (UPID) helpers.

Utilities for working with Proxmox asynchronous tasks: parse node names from UPID strings
returned by write API calls, and poll ``/nodes/{node}/tasks/{upid}/status`` until a task
reports ``status`` of ``stopped``.

Used by guest write tools when ``wait_for_completion=true`` is requested.
"""

import asyncio
from typing import Any

from proxmox_ve_mcp.client.http import PveClient


def parse_upid_node(upid: str) -> str | None:
    """Extract the node name from a Proxmox UPID string.

    Proxmox UPIDs follow ``UPID:node:pid:starttime:hex:type:user@realm:`` (additional
    colon-separated fields may follow).

    Args:
        upid: Task identifier returned by a mutating API call (for example
            ``UPID:pvenode-001:001:ABC:start:u@pam:``).

    Returns:
        Node short name when *upid* starts with ``UPID:`` and has at least two segments;
        otherwise ``None``.
    """
    parts = upid.split(":")
    if len(parts) >= 2 and parts[0] == "UPID":
        return parts[1]
    return None


async def wait_for_task(
    client: PveClient,
    node: str,
    upid: str,
    *,
    timeout_sec: float = 120.0,
    poll_interval_sec: float = 2.0,
) -> dict[str, Any]:
    """Poll task status until the task stops or the timeout elapses.

    Repeatedly calls ``GET /nodes/{node}/tasks/{upid}/status`` via *client* until the
    response ``status`` field equals ``stopped``, or until *timeout_sec* expires. Does not
    interpret ``exitstatus``; callers inspect the returned dict for success or failure.

    Args:
        client: Authenticated Proxmox HTTP client used for status polling.
        node: Node that owns the task (must match the UPID node segment).
        upid: Full UPID string from the originating write operation.
        timeout_sec: Maximum seconds to wait before raising :exc:`TimeoutError`.
        poll_interval_sec: Seconds to sleep between status polls.

    Returns:
        Last status dictionary from the Proxmox API (typically includes ``status``,
        ``exitstatus``, and ``upid`` when the task has stopped).

    Raises:
        TimeoutError: When the task does not reach ``stopped`` within *timeout_sec*.
        PveApiError: When a status poll fails (transport, HTTP error, or API errors).
    """
    deadline = asyncio.get_running_loop().time() + timeout_sec
    last_status: dict[str, Any] = {}

    while asyncio.get_running_loop().time() < deadline:
        raw = await client.get(f"/nodes/{node}/tasks/{upid}/status")
        if isinstance(raw, dict):
            last_status = raw
            if raw.get("status") == "stopped":
                return last_status
        await asyncio.sleep(poll_interval_sec)

    raise TimeoutError(
        f"Task {upid} on {node} did not finish within {timeout_sec}s; "
        f"last status: {last_status.get('status', 'unknown')}"
    )
