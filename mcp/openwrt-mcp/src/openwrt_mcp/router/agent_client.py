"""Typed client for the router agent protocol (see docs/AGENT_CONTRACT.md)."""

from typing import Any

from openwrt_mcp.constants import AGENT_PROTOCOL_VERSION
from openwrt_mcp.errors import (
    ApprovalExpired,
    ApprovalRequired,
    DomainError,
    NotFound,
    OperationProhibited,
    RouterError,
    StatePreconditionFailed,
    TargetLocked,
    VerificationFailed,
)
from openwrt_mcp.router.transport import RouterTransport

_AGENT_ERRORS: dict[str, type[DomainError]] = {
    "OPERATION_PROHIBITED": OperationProhibited,
    "APPROVAL_INVALID": ApprovalRequired,
    "APPROVAL_EXPIRED": ApprovalExpired,
    "STATE_PRECONDITION_FAILED": StatePreconditionFailed,
    "TARGET_LOCKED": TargetLocked,
    "VALIDATION_FAILED": VerificationFailed,
    "NOT_FOUND": NotFound,
}


class AgentClient:
    """Thin wrapper mapping agent error codes to domain errors."""

    def __init__(self, transport: RouterTransport) -> None:
        self._t = transport

    async def _request(self, op: str, timeout: float | None = None, **fields: Any) -> dict[str, Any]:
        """Send one agent request and map failures to domain errors."""
        resp = await self._t.call({"v": AGENT_PROTOCOL_VERSION, "op": op, **fields}, timeout=timeout)
        if resp.get("ok") is True:
            return resp
        err = resp.get("error") or {}
        code = str(err.get("code", "ROUTER_ERROR"))
        message = str(err.get("message", "router agent error"))[:300]
        cls = _AGENT_ERRORS.get(code)
        if cls is not None:
            raise cls(message)
        raise RouterError(message, code=code if code.isupper() else "ROUTER_ERROR")

    async def inspect(self) -> dict[str, Any]:
        """Return router firewall state."""
        return await self._request("inspect")

    async def validate(self, operations: list[dict[str, Any]], state_precondition: str) -> dict[str, Any]:
        """Dry-run validation of candidate operations."""
        return await self._request("validate", operations=operations, state_precondition=state_precondition)

    async def apply(self, **fields: Any) -> dict[str, Any]:
        """Apply an approved plan (agent re-verifies everything)."""
        return await self._request("apply", timeout=120.0, **fields)

    async def confirm(self, plan_id: str) -> dict[str, Any]:
        """Confirm a pending transaction."""
        return await self._request("confirm", plan_id=plan_id)

    async def rollback(self, plan_id: str) -> dict[str, Any]:
        """Roll back a transaction."""
        return await self._request("rollback", timeout=120.0, plan_id=plan_id)

    async def status(self, plan_id: str | None = None) -> dict[str, Any]:
        """Return journal status."""
        fields: dict[str, Any] = {"plan_id": plan_id} if plan_id else {}
        return await self._request("status", **fields)
