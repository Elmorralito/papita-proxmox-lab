"""Proxmox task (UPID) helpers.

Utilities for working with Proxmox asynchronous tasks: parse node names from UPID strings
returned by write API calls, and poll ``/nodes/{node}/tasks/{upid}/status`` until a task
reports ``status`` of ``stopped``.

Used by guest write tools when ``wait_for_completion=true`` is requested.
"""

import asyncio
from typing import Any

from proxmox_ve_mcp.client.errors import PveApiError
from proxmox_ve_mcp.client.http import PveClient
from proxmox_ve_mcp.constants import API_LOST_ERROR_CODES, MAX_WAIT_CALL_SEC


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


def task_succeeded(status: dict[str, Any]) -> bool:
    """True when a stopped task reports ``exitstatus`` ``OK``."""
    return status.get("status") == "stopped" and status.get("exitstatus") == "OK"


def node_states(entries: list[Any]) -> dict[str, str]:
    """Map node name → ``online``/``offline`` from ``/cluster/status`` node entries."""
    states: dict[str, str] = {}
    for entry in entries:
        if isinstance(entry, dict) and entry.get("type") == "node" and entry.get("name"):
            states[str(entry["name"])] = "online" if entry.get("online") else "offline"
    return states


async def wait_for_nodes_state(
    client: PveClient,
    nodes: list[str] | None,
    target: str,
    *,
    timeout_sec: float = MAX_WAIT_CALL_SEC,
    poll_interval_sec: float = 5.0,
) -> dict[str, Any]:
    """Poll ``GET /cluster/status`` until *nodes* reach *target* (``online``/``offline``).

    When waiting for ``offline`` and the API host itself stops answering (entry node powered
    off), the wait ends with ``api_lost=True`` and every unconfirmed node reported as
    ``offline_assumed``.

    Args:
        client: Authenticated Proxmox HTTP client.
        nodes: Node names to watch; ``None`` watches every cluster member.
        target: ``online`` or ``offline``.
        timeout_sec: Maximum seconds to wait (does not raise on timeout).
        poll_interval_sec: Seconds between polls.

    Returns:
        ``reached``, ``api_lost``, per-node ``states``, ``pending`` nodes, and ``elapsed_s``.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    deadline = started + timeout_sec
    states: dict[str, str] = {}
    watched: list[str] = list(nodes) if nodes else []

    while True:
        try:
            raw = await client.get("/cluster/status")
        except PveApiError as exc:
            if target == "offline" and exc.code in API_LOST_ERROR_CODES:
                for name in watched:
                    if states.get(name) != "offline":
                        states[name] = "offline_assumed"
                return {
                    "reached": True,
                    "api_lost": True,
                    "api_error": exc.code,
                    "states": states,
                    "pending": [],
                    "elapsed_s": round(loop.time() - started, 1),
                }
            raise

        current = node_states(raw if isinstance(raw, list) else [])
        if not watched:
            watched = sorted(current)
        unknown = [name for name in watched if name not in current]
        if unknown:
            raise ValueError(f"Unknown cluster node(s): {', '.join(unknown)}")
        states = {name: current[name] for name in watched}
        pending = [name for name in watched if states[name] != target]
        now = loop.time()
        if not pending or now >= deadline:
            return {
                "reached": not pending,
                "api_lost": False,
                "states": states,
                "pending": pending,
                "elapsed_s": round(now - started, 1),
            }
        await asyncio.sleep(min(poll_interval_sec, max(deadline - now, 0.0)))
