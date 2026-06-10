"""Standard JSON responses for MCP tools.

Provides success and error payload builders plus decorators that wrap async tool
implementations with timing, structured logging, and consistent exception handling.
"""

import json
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from proxmox_ve_mcp.client.errors import PveApiError
from proxmox_ve_mcp.logging_config import log_tool_event
from proxmox_ve_mcp.tools.meta import tool_meta

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def ok_response(
    tool: str,
    data: Any,
    *,
    duration_ms: int,
    warnings: list[str] | None = None,
    meta_extra: dict[str, Any] | None = None,
) -> str:
    """Serialize a successful tool result as indented JSON.

    Args:
        tool: Registered MCP tool name included in ``meta``.
        data: Tool-specific payload placed under ``data``.
        duration_ms: Execution time in milliseconds for ``meta``.
        warnings: Optional non-fatal messages included under ``warnings``.
        meta_extra: Additional fields merged into ``meta`` via :func:`tool_meta`.

    Returns:
        JSON string with ``ok: true``, ``data``, ``warnings``, and ``meta`` keys.
    """
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
    """Serialize a failed tool invocation as indented JSON.

    :class:`~proxmox_ve_mcp.client.errors.PveApiError` instances are converted with
    :meth:`PveApiError.to_dict`; other exceptions become ``INTERNAL_ERROR``.

    Args:
        tool: Registered MCP tool name included in ``meta``.
        exc: Exception raised by the tool implementation.
        duration_ms: Execution time in milliseconds for ``meta``.
        meta_extra: Additional fields merged into ``meta`` via :func:`tool_meta`.

    Returns:
        JSON string with ``ok: false``, ``error``, and ``meta`` keys.
    """
    if isinstance(exc, PveApiError):
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
    """Wrap async tool implementations with timing, logging, and error JSON.

    On success, returns the wrapped function's string result unchanged. On any exception,
    logs the failure and returns :func:`error_response` JSON instead of raising.

    Args:
        tool_name: Name used for logging and error payload ``meta``.

    Returns:
        Decorator that wraps an async tool implementation.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> str:
            """Execute the tool, log timing, and return JSON errors instead of raising."""
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
    mutating: bool = True,
    audit_fields: tuple[str, ...] = (),
) -> Callable[[F], F]:
    """Wrap mutating tools with audit logging and error JSON.

    Like :func:`tool_handler`, but logs selected keyword arguments from *audit_fields* on
    both success and failure for traceability of write operations.

    Args:
        tool_name: Name used for logging and error payload ``meta``.
        mutating: When ``True``, included in log events as a mutating operation.
        audit_fields: Keyword argument names to capture from the tool invocation (for
            example ``node``, ``vmid``).

    Returns:
        Decorator that wraps an async write tool implementation.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> str:
            """Execute the tool, log timing, and return JSON errors instead of raising."""
            started = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                duration_ms = int((time.perf_counter() - started) * 1000)
                audit = {field: kwargs.get(field) for field in audit_fields if field in kwargs}
                log_tool_event(
                    tool_name,
                    duration_ms=duration_ms,
                    status="ok",
                    mutating=mutating,
                    **audit,
                )
                return result
            except Exception as exc:
                duration_ms = int((time.perf_counter() - started) * 1000)
                audit = {field: kwargs.get(field) for field in audit_fields if field in kwargs}
                log_tool_event(
                    tool_name,
                    duration_ms=duration_ms,
                    status="error",
                    mutating=mutating,
                    error_type=type(exc).__name__,
                    **audit,
                )
                return error_response(tool_name, exc, duration_ms=duration_ms)

        return wrapper  # type: ignore[return-value]

    return decorator
