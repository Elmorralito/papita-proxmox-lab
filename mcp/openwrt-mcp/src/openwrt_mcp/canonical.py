"""Canonical JSON and plan digests (must match the ucode router agent byte for byte)."""

import hashlib
import re
from typing import Any

_SAFE = re.compile(r"^[A-Za-z0-9_./:@-]*$")


def canonical_json(value: Any) -> str:
    """Serialize ``value`` with sorted keys, no whitespace, ints/bools/safe strings only.

    Raises:
        ValueError: For floats, ``None`` or strings outside the safe charset.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        if not _SAFE.match(value):
            raise ValueError("string contains characters outside the canonical-safe charset")
        return '"' + value + '"'
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    if isinstance(value, dict):
        parts = []
        for key in sorted(value):
            if not isinstance(key, str):
                raise ValueError("object keys must be strings")
            parts.append(canonical_json(key) + ":" + canonical_json(value[key]))
        return "{" + ",".join(parts) + "}"
    raise ValueError(f"unsupported type in canonical JSON: {type(value).__name__}")


def sha256_digest(text: str) -> str:
    """Return ``sha256:<hex>`` for UTF-8 text."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def plan_digest(
    *,
    router_id: str,
    operations: list[dict[str, Any]],
    state_precondition: str,
    policy_revision: int,
    recovery: dict[str, Any],
) -> str:
    """Compute the immutable plan digest."""
    return sha256_digest(
        canonical_json(
            {
                "router_id": router_id,
                "operations": operations,
                "state_precondition": state_precondition,
                "policy_revision": policy_revision,
                "recovery": recovery,
            }
        )
    )
