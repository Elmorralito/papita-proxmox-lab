"""TrueNAS API client errors."""

from typing import Any


class TnasApiError(Exception):
    """Raised when the TrueNAS WebSocket API returns an error."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "TRUENAS_API_ERROR",
        method: str | None = None,
        details: Any = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.method = method
        self.details = details
        self.hint = hint

    def to_dict(self) -> dict[str, Any]:
        """Serialize the error for MCP JSON tool responses."""
        body: dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.hint:
            body["hint"] = self.hint
        if self.method:
            body["method"] = self.method
        if self.details is not None:
            body["details"] = self.details
        return body
