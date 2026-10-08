"""Stable domain errors (no secrets, no tracebacks)."""

import json
from typing import Any


class DomainError(Exception):
    """Error with a stable machine-readable code."""

    code = "INTERNAL"
    retryable = False

    def __init__(self, message: str, *, code: str | None = None, retryable: bool | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        if retryable is not None:
            self.retryable = retryable
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        """Return the structured error payload."""
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


class InvalidInput(DomainError):
    """Tool input failed validation."""

    code = "INVALID_INPUT"


class NotFound(DomainError):
    """Plan or resource not found."""

    code = "NOT_FOUND"


class OperationProhibited(DomainError):
    """Operation denied even with human approval."""

    code = "OPERATION_PROHIBITED"


class ApprovalRequired(DomainError):
    """No valid, unexpired, plan-bound grant."""

    code = "APPROVAL_REQUIRED"


class ApprovalExpired(DomainError):
    """Grant or plan expired."""

    code = "APPROVAL_EXPIRED"


class StatePreconditionFailed(DomainError):
    """Router configuration changed since planning."""

    code = "STATE_PRECONDITION_FAILED"


class TargetNotAuthorized(DomainError):
    """Caller lacks target or scope."""

    code = "TARGET_NOT_AUTHORIZED"


class TargetLocked(DomainError):
    """Another transaction is pending."""

    code = "TARGET_LOCKED"


class VerificationFailed(DomainError):
    """Verification failed; recovery executed or escalated."""

    code = "VERIFICATION_FAILED"


class RouterError(DomainError):
    """Router transport or agent failure."""

    code = "ROUTER_ERROR"
    retryable = True


def error_result(exc: DomainError) -> str:
    """Serialize a domain error as the tool JSON payload."""
    return json.dumps({"isError": True, "error": exc.to_dict()}, indent=2, sort_keys=True)
