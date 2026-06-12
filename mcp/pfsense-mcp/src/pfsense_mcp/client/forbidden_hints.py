"""Actionable hints for pfREST HTTP 403 responses."""

from __future__ import annotations

from pfsense_mcp.constants import DEFAULT_API_USER, LAB_PFSENSE_LAN_IP

SETUP_DOC = "mcp/pfsense-mcp/docs/PFSENSE_API_KEY_SETUP.md"


def forbidden_hint(
    *,
    status_code: int | None,
    message: str | None,
    response_id: str | None,
    endpoint: str | None,
    host: str | None,
    api_user: str | None = None,
) -> str | None:
    """Return an operator-facing hint for pfREST HTTP 401/403 responses.

    Args:
        status_code: HTTP status from pfREST, if known.
        message: Error message body from pfREST.
        response_id: pfREST machine-readable response identifier.
        endpoint: API path that failed (for privilege hints).
        host: Configured ``PFSENSE_HOST`` (used for Tailscale vs LAN guidance).
        api_user: Local pfSense user that owns the API key.

    Returns:
        Actionable setup hint, or ``None`` when the status is not 401/403.
    """
    user = (api_user or DEFAULT_API_USER).strip() or DEFAULT_API_USER
    if status_code not in (401, 403):
        return None

    if status_code == 401:
        return (
            f"pfREST rejected the API key (HTTP 401). Regenerate under System → REST API → Keys "
            f"for user `{user}` and update PFSENSE_API_KEY in ~/.cursor/mcp.json. "
            f"See {SETUP_DOC}."
        )

    if response_id == "ENDPOINT_INTERFACE_NOT_ALLOWED":
        return (
            "pfREST rejected the request because HTTPS arrived on a non-allowed interface "
            f"(common when PFSENSE_HOST is a Tailscale IP like {host or '100.x.x.x'}). "
            f"On pfSense: System → REST API → Settings → Allowed Interfaces — **deselect all** "
            "(empty list allows Tailscale; Tailscale is not selectable). Or use LAN IP "
            f"{LAB_PFSENSE_LAN_IP} when the subnet route is active. See {SETUP_DOC}."
        )

    lowered = (message or "").lower()
    if response_id is None and host and host.startswith("100.") and "admin policy" in lowered:
        return (
            "pfREST rejected the request because HTTPS arrived on a non-allowed interface "
            f"(PFSENSE_HOST={host} is a Tailscale IP). "
            f"On pfSense: System → REST API → Settings → Allowed Interfaces — **deselect all**. "
            f"Or run ./deploy/pfsense-restapi-access.sh fix-access. See {SETUP_DOC}."
        )

    if response_id == "ENDPOINT_CLIENT_NOT_ALLOWED_BY_ACL":
        return (
            "pfREST Access List denied this client. On pfSense: System → REST API → Access Lists — "
            f"allow your workstation / tailnet source IP. See {SETUP_DOC}."
        )

    if "admin policy" in lowered and response_id != "ENDPOINT_CLIENT_NOT_ALLOWED_BY_ACL":
        return (
            "pfREST admin policy blocked the call (allowed interfaces or access list). "
            f"See {SETUP_DOC} § Restrict access."
        )

    if "privilege" in lowered or "authorisation" in lowered or "authorization" in lowered:
        return (
            "API user lacks GET privilege for this endpoint. "
            f"Grant endpoint privileges to {user} in System → User Manager. See {SETUP_DOC}."
        )

    if endpoint:
        return f"Grant the API user GET privilege on {endpoint}. See {SETUP_DOC}."

    return f"Grant the API user GET privileges for pfREST reads. See {SETUP_DOC}."
