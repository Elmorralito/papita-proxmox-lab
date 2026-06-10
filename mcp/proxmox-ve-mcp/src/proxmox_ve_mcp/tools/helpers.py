"""Shared helpers for MCP tool implementations.

Utilities for normalizing Proxmox API list payloads, redacting secrets from guest configs,
enforcing write confirmations, validating guest types, and parsing Pydantic tool inputs.
"""

from typing import Any

from pydantic import BaseModel

REDACT_KEY_FRAGMENTS = (
    "password",
    "secret",
    "sshkey",
    "token",
    "cipassword",
    "cicustom",
    "keyfile",
)


def normalize_list(data: Any) -> list[dict[str, Any]]:
    """Coerce Proxmox list responses into a list of dictionaries.

    Proxmox sometimes returns a single object instead of a one-element list. This helper
    normalizes both shapes for consistent tool output.

    Args:
        data: Raw ``data`` field from a Proxmox API response.

    Returns:
        List of dict items when *data* is a list of dicts, ``[data]`` when *data* is a
        dict, or an empty list for other types.
    """
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def redact_config(data: Any) -> Any:
    """Remove secrets from guest config payloads before returning to agents.

    Recursively walks dicts and lists. Keys whose lowercase form contains a fragment from
    :data:`REDACT_KEY_FRAGMENTS` are replaced with ``[REDACTED]``.

    Args:
        data: Guest configuration tree from the Proxmox API.

    Returns:
        A copy of *data* with sensitive key values redacted; non-container values unchanged.
    """
    if isinstance(data, dict):
        redacted: dict[str, Any] = {}
        for key, value in data.items():
            key_lower = key.lower()
            if any(fragment in key_lower for fragment in REDACT_KEY_FRAGMENTS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_config(value)
        return redacted
    if isinstance(data, list):
        return [redact_config(item) for item in data]
    return data


def require_confirm(confirm: bool) -> None:
    """Reject mutating operations unless confirm is explicitly true.

    Args:
        confirm: Caller acknowledgment flag; must be exactly ``True``.

    Raises:
        ValueError: When *confirm* is not ``True``.
    """
    if confirm is not True:
        message = (
            "Mutating operation rejected: confirm must be true. "
            + "Re-run with confirm=true after verifying the target."
        )
        raise ValueError(message)


def normalize_guest_type(guest_type: str) -> str:
    """Normalize and validate a guest type string.

    Args:
        guest_type: Raw guest type from tool input (for example ``QEMU`` or `` lxc ``).

    Returns:
        Lowercase ``qemu`` or ``lxc``.

    Raises:
        ValueError: When the normalized value is not ``qemu`` or ``lxc``.
    """
    normalized = guest_type.strip().lower()
    if normalized not in {"qemu", "lxc"}:
        raise ValueError("guest_type must be 'qemu' or 'lxc'")
    return normalized


def parse_model(model: type[BaseModel], **kwargs: Any) -> BaseModel:
    """Validate tool inputs via a Pydantic model.

    Args:
        model: Schema class defining allowed fields and validators.
        **kwargs: Raw keyword arguments from the MCP tool invocation.

    Returns:
        Validated model instance.

    Raises:
        pydantic.ValidationError: When *kwargs* fail model or field validation.
    """
    return model.model_validate(kwargs)
