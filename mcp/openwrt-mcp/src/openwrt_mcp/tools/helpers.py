"""Shared helpers for tool implementations."""

import functools
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from openwrt_mcp.errors import DomainError, InvalidInput, error_result

logger = logging.getLogger("openwrt_mcp.tools")

REDACT_KEY_FRAGMENTS = ("password", "secret", "token", "privatekey", "psk", "key")
_SAFE_KEYS = {"idempotency_key"}
MAX_TEXT = 300


def redact_sensitive(data: Any) -> Any:
    """Redact values whose keys look like secrets and truncate long strings."""
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            lowered = str(key).lower()
            if key not in _SAFE_KEYS and any(f in lowered for f in REDACT_KEY_FRAGMENTS):
                out[key] = "[REDACTED]"
            else:
                out[key] = redact_sensitive(value)
        return out
    if isinstance(data, list):
        return [redact_sensitive(item) for item in data]
    if isinstance(data, str) and len(data) > MAX_TEXT:
        return data[:MAX_TEXT] + "...[truncated]"
    return data


def ok_result(data: dict[str, Any]) -> str:
    """Serialize a successful result."""
    return json.dumps({"isError": False, "structuredContent": redact_sensitive(data)}, indent=2, sort_keys=True)


def iso(epoch: int | None) -> str | None:
    """Epoch seconds to UTC ISO-8601."""
    if epoch is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def guarded(fn: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
    """Convert errors into stable payloads (no secrets, no tracebacks)."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        """Run the tool and convert domain errors to results."""
        try:
            return await fn(*args, **kwargs)
        except DomainError as exc:
            return error_result(exc)
        except ValidationError as exc:
            fields = ", ".join(sorted({".".join(str(p) for p in e["loc"]) or "?" for e in exc.errors()}))
            return error_result(InvalidInput(f"invalid fields: {fields}"))
        except Exception:  # pylint: disable=broad-except
            logger.exception("unexpected tool failure")
            return error_result(DomainError("internal error; see server logs"))

    return wrapper
