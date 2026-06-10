"""Helpers for Proxmox API permission errors and token diagnostics.

Parses Proxmox ``Permission check failed (path, privilege)`` messages from HTTP 403 responses,
builds actionable hints about API token ACLs (privilege separation), and enriches
``PVE_FORBIDDEN`` error dictionaries for MCP tool output.

Public helpers: :func:`parse_permission_message`, :func:`permission_hint`,
:func:`enrich_forbidden_error`, and :data:`TOKEN_ACL_HINT` (reused by diagnostics and smoke tests).
"""

from __future__ import annotations

import re
from typing import Any

PERMISSION_CHECK_RE = re.compile(r"Permission check failed \((?P<path>[^,]+),\s*(?P<privilege>[^)]+)\)")

TOKEN_ACL_HINT = (
    "API tokens use privilege separation by default: permissions come from the "
    "role assigned to the token at path /, not from the owning user (including root@pam). "
    "Datacenter → Permissions → add role MCPAgentRead or Administrator to the token "
    "(API Token permission entry), or disable Privilege Separation on the token. "
    "See mcp/proxmox-ve-mcp/docs/PVE_TOKEN_SETUP.md."
)


def parse_permission_message(message: str | None) -> dict[str, str | None]:
    """Extract ACL path and privilege from a Proxmox permission error message.

    Args:
        message: Raw ``message`` from a Proxmox JSON body, often
            ``Permission check failed (/, Sys.Audit)``.

    Returns:
        Dictionary with ``path`` and ``privilege`` keys. Each value is the parsed string, or
        ``None`` when *message* is empty or does not match the expected pattern.
    """
    if not message:
        return {"path": None, "privilege": None}
    match = PERMISSION_CHECK_RE.search(message)
    if not match:
        return {"path": None, "privilege": None}
    return {
        "path": match.group("path").strip(),
        "privilege": match.group("privilege").strip(),
    }


def permission_hint(
    *,
    status_code: int | None,
    message: str | None = None,
    endpoint: str | None = None,
) -> str | None:
    """Return an actionable hint for common Proxmox permission failures.

    Only HTTP 403 responses produce a hint. When the message names ``Sys.Audit``, the hint
    calls out that privilege explicitly; otherwise a general token ACL guidance string is
    returned (:data:`TOKEN_ACL_HINT`).

    Args:
        status_code: HTTP status code from the failed API call.
        message: Proxmox ``message`` field, used to parse required path and privilege.
        endpoint: Fallback path when the message cannot be parsed (for example
            ``/cluster/config/nodes``).

    Returns:
        Human-readable remediation text, or ``None`` when *status_code* is not 403.
    """
    if status_code != 403:
        return None

    parsed = parse_permission_message(message)
    privilege = parsed.get("privilege") or "required privilege"
    path = parsed.get("path") or endpoint or "/"

    if privilege == "Sys.Audit":
        return (
            f"Missing Sys.Audit on {path}. Assign Sys.Audit (or Administrator) to the "
            f"API token at /. {TOKEN_ACL_HINT}"
        )

    return TOKEN_ACL_HINT


def enrich_forbidden_error(error_dict: dict[str, Any]) -> dict[str, Any]:
    """Add parsed permission fields and a hint to a ``PVE_FORBIDDEN`` error body.

    Mutates *error_dict* in place. Reads ``pve_message`` or ``message``, ``status_code``, and
    ``endpoint`` when present. Used by :meth:`~proxmox_ve_mcp.client.errors.PveApiError.to_dict`
    after the base forbidden fields are assembled.

    Args:
        error_dict: Serializable error mapping (typically from :meth:`PveApiError.to_dict`).

    Returns:
        The same *error_dict* reference, possibly updated with ``required_path``,
        ``required_privilege``, and ``hint`` keys.
    """
    message = error_dict.get("pve_message") or error_dict.get("message")
    if isinstance(message, str):
        parsed = parse_permission_message(message)
        if parsed["path"]:
            error_dict["required_path"] = parsed["path"]
        if parsed["privilege"]:
            error_dict["required_privilege"] = parsed["privilege"]

    hint = permission_hint(
        status_code=error_dict.get("status_code"),
        message=message if isinstance(message, str) else None,
        endpoint=error_dict.get("endpoint"),
    )
    if hint:
        error_dict["hint"] = hint
    return error_dict
