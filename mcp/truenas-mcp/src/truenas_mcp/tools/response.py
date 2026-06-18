"""Standard JSON responses for MCP tools."""

import json
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from truenas_mcp.client.errors import TnasApiError
from truenas_mcp.constants import RUNBOOK_REFS
from truenas_mcp.logging_config import log_tool_event
from truenas_mcp.tools.registry import TOOL_REGISTRY

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def tool_meta(tool: str, duration_ms: int, **extra: Any) -> dict[str, Any]:
    """Build standard metadata attached to every tool JSON response."""
    meta: dict[str, Any] = {"tool": tool, "duration_ms": duration_ms}
    tool_class = TOOL_REGISTRY.get(tool)
    if tool_class is not None:
        meta["tool_class"] = tool_class.value
    runbook = RUNBOOK_REFS.get(tool)
    if runbook and "runbook_ref" not in extra:
        meta["runbook_ref"] = runbook
    meta.update(extra)
    return meta


def ok_response(
    tool: str,
    data: Any,
    *,
    duration_ms: int,
    warnings: list[str] | None = None,
    meta_extra: dict[str, Any] | None = None,
) -> str:
    """Serialize a successful tool result as indented JSON for MCP clients."""
    payload = {
        "ok": True,
        "data": data,
        "warnings": warnings or [],
        "meta": tool_meta(tool, duration_ms, **(meta_extra or {})),
    }
    return json.dumps(payload, indent=2, default=str)


def error_response(
    tool: str,
    exc: Exception,
    *,
    duration_ms: int,
    meta_extra: dict[str, Any] | None = None,
) -> str:
    """Serialize a tool failure as indented JSON."""
    if isinstance(exc, TnasApiError):
        error_body = exc.to_dict()
    else:
        error_body = {"code": "INTERNAL_ERROR", "message": str(exc)}
    payload = {
        "ok": False,
        "error": error_body,
        "meta": tool_meta(tool, duration_ms, **(meta_extra or {})),
    }
    return json.dumps(payload, indent=2, default=str)


def tool_handler(tool_name: str) -> Callable[[F], F]:
    """Wrap async tool implementations with timing, logging, and error JSON responses."""

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> str:
            started = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                duration_ms = int((time.perf_counter() - started) * 1000)
                log_tool_event(tool_name, duration_ms=duration_ms, status="ok")
                return result
            except Exception as exc:
                duration_ms = int((time.perf_counter() - started) * 1000)
                log_tool_event(
                    tool_name,
                    duration_ms=duration_ms,
                    status="error",
                    error_type=type(exc).__name__,
                )
                return error_response(tool_name, exc, duration_ms=duration_ms)

        return wrapper  # type: ignore[return-value]

    return decorator


def write_tool_handler(
    tool_name: str,
    *,
    audit_fields: tuple[str, ...] = (),
) -> Callable[[F], F]:
    """Wrap mutating tools with audit logging."""

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> str:
            started = time.perf_counter()
            audit = {field: kwargs.get(field) for field in audit_fields if field in kwargs}
            try:
                result = await func(*args, **kwargs)
                duration_ms = int((time.perf_counter() - started) * 1000)
                log_tool_event(tool_name, duration_ms=duration_ms, status="ok", mutating=True, **audit)
                return result
            except Exception as exc:
                duration_ms = int((time.perf_counter() - started) * 1000)
                log_tool_event(
                    tool_name,
                    duration_ms=duration_ms,
                    status="error",
                    mutating=True,
                    error_type=type(exc).__name__,
                    **audit,
                )
                return error_response(tool_name, exc, duration_ms=duration_ms)

        return wrapper  # type: ignore[return-value]

    return decorator
