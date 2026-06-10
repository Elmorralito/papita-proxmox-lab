"""Exception types for Proxmox VE HTTP and API failures.

Defines :class:`PveApiError`, raised by :class:`~proxmox_ve_mcp.client.http.PveClient` when
transport fails, HTTP status indicates an error, or the JSON body contains Proxmox ``errors``.
Tool handlers serialize instances via :meth:`PveApiError.to_dict` into MCP JSON error responses
with stable ``code`` values and optional permission hints for HTTP 403 responses.
"""

from typing import Any

from proxmox_ve_mcp.client.permissions import enrich_forbidden_error, permission_hint


class PveApiError(Exception):
    """Raised when the Proxmox API returns an error or HTTP failure.

    Captures HTTP status, optional Proxmox ``errors`` payload, human-readable ``message`` field
    from the API body, and the request path for diagnostics. Use :meth:`to_dict` when building
    structured tool responses.

    Attributes:
        status_code: HTTP status from the response, if available.
        pve_errors: Proxmox ``errors`` object from the JSON body, when present.
        pve_message: Top-level ``message`` string from the Proxmox JSON body, when present.
        endpoint: Normalized API path (for example ``/cluster/config/nodes``) for the failed call.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        pve_errors: Any = None,
        pve_message: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        """Initialize a Proxmox API error with optional response metadata.

        Args:
            message: Human-readable summary; also used as :exc:`Exception` message text.
            status_code: HTTP response status code, if the failure reached the server.
            pve_errors: Structured errors from the Proxmox JSON ``errors`` field.
            pve_message: Raw ``message`` field from the Proxmox JSON body (often permission text).
            endpoint: API path that was requested when the error occurred.
        """
        super().__init__(message)
        self.status_code = status_code
        self.pve_errors = pve_errors
        self.pve_message = pve_message
        self.endpoint = endpoint

    def to_dict(self) -> dict[str, Any]:
        """Serialize the error for MCP JSON tool responses.

        Maps ``status_code`` to a stable ``code`` string:

        * ``401`` → ``PVE_UNAUTHORIZED``
        * ``403`` → ``PVE_FORBIDDEN`` (includes ``hint``, ``required_path``, ``required_privilege``)
        * ``>= 500`` → ``PVE_SERVER_ERROR``
        * otherwise → ``PVE_ERROR``

        Returns:
            Dictionary suitable for the ``error`` field in tool JSON output, including
            ``message``, ``status_code``, ``pve_errors``, and optional ``pve_message``,
            ``endpoint``, and ``hint`` keys.
        """
        code = "PVE_ERROR"
        if self.status_code == 401:
            code = "PVE_UNAUTHORIZED"
        elif self.status_code == 403:
            code = "PVE_FORBIDDEN"
        elif self.status_code is not None and self.status_code >= 500:
            code = "PVE_SERVER_ERROR"

        body: dict[str, Any] = {
            "code": code,
            "message": str(self),
            "status_code": self.status_code,
            "pve_errors": self.pve_errors,
        }
        if self.pve_message:
            body["pve_message"] = self.pve_message
        if self.endpoint:
            body["endpoint"] = self.endpoint

        hint = permission_hint(
            status_code=self.status_code,
            message=self.pve_message,
            endpoint=self.endpoint,
        )
        if hint:
            body["hint"] = hint

        if code == "PVE_FORBIDDEN":
            enrich_forbidden_error(body)

        return body
