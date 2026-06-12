"""Exception types for pfREST HTTP and API failures."""

from typing import Any

from pfsense_mcp.client.forbidden_hints import forbidden_hint


class PfsApiError(Exception):
    """Raised when pfREST returns an error or HTTP failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        pfrest_code: int | None = None,
        pfrest_status: str | None = None,
        pfrest_message: str | None = None,
        pfrest_response_id: str | None = None,
        endpoint: str | None = None,
        host: str | None = None,
        api_user: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.pfrest_code = pfrest_code
        self.pfrest_status = pfrest_status
        self.pfrest_message = pfrest_message
        self.pfrest_response_id = pfrest_response_id
        self.endpoint = endpoint
        self.host = host
        self.api_user = api_user

    def to_dict(self) -> dict[str, Any]:
        """Serialize the error for MCP tool JSON responses and operator hints."""
        code = "PFS_ERROR"
        if self.status_code == 401:
            code = "PFS_UNAUTHORIZED"
        elif self.status_code == 403:
            code = "PFS_FORBIDDEN"
        elif self.status_code == 404:
            code = "PFS_NOT_FOUND"
        elif self.status_code is not None and self.status_code >= 500:
            code = "PFS_SERVER_ERROR"
        elif self.pfrest_code is not None and self.pfrest_code != 200:
            code = "PFS_API_ERROR"

        body: dict[str, Any] = {
            "code": code,
            "message": str(self),
            "status_code": self.status_code,
            "pfrest_code": self.pfrest_code,
        }
        if self.pfrest_message:
            body["pfrest_message"] = self.pfrest_message
        if self.pfrest_response_id:
            body["pfrest_response_id"] = self.pfrest_response_id
        if self.endpoint:
            body["endpoint"] = self.endpoint

        hint = forbidden_hint(
            status_code=self.status_code,
            message=self.pfrest_message or str(self),
            response_id=self.pfrest_response_id,
            endpoint=self.endpoint,
            host=self.host,
            api_user=self.api_user,
        )
        if hint:
            body["hint"] = hint
        return body

    @classmethod
    def from_http(
        cls,
        status_code: int,
        payload: Any,
        *,
        endpoint: str,
        host: str | None = None,
        api_user: str | None = None,
    ) -> "PfsApiError":
        """Build an error from a non-success HTTP status and response payload."""
        message = f"pfREST HTTP {status_code}"
        pfrest_message = None
        pfrest_response_id = None
        if isinstance(payload, dict):
            pfrest_message = payload.get("message")
            response_id = payload.get("response_id")
            if isinstance(response_id, str) and response_id:
                pfrest_response_id = response_id
            if isinstance(pfrest_message, str) and pfrest_message:
                message = f"pfREST HTTP {status_code}: {pfrest_message}"
        elif isinstance(payload, str) and payload.strip():
            snippet = payload.strip().replace("\n", " ")[:160]
            message = f"pfREST HTTP {status_code}: {snippet}"
        return cls(
            message,
            status_code=status_code,
            pfrest_message=pfrest_message if isinstance(pfrest_message, str) else None,
            pfrest_response_id=pfrest_response_id,
            endpoint=endpoint,
            host=host,
            api_user=api_user,
        )

    @classmethod
    def from_transport(
        cls,
        message: str,
        *,
        endpoint: str | None = None,
        host: str | None = None,
        api_user: str | None = None,
    ) -> "PfsApiError":
        """Build an error from an httpx transport or TLS failure."""
        lowered = message.lower()
        if "certificate verify failed" in lowered or "ssl" in lowered:
            return cls(
                message,
                endpoint=endpoint,
                host=host,
                api_user=api_user,
            )
        return cls(message, endpoint=endpoint, host=host, api_user=api_user)

    @classmethod
    def from_pfrest(cls, payload: dict[str, Any], *, endpoint: str) -> "PfsApiError":
        """Build an error from a pfREST envelope with a non-200 ``code`` field."""
        code = payload.get("code")
        status = payload.get("status")
        message = payload.get("message") or f"pfREST error (code={code})"
        return cls(
            str(message),
            status_code=200,
            pfrest_code=int(code) if isinstance(code, int) else None,
            pfrest_status=str(status) if status is not None else None,
            pfrest_message=str(message),
            endpoint=endpoint,
        )
