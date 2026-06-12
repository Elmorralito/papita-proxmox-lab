"""Shared helpers for tool implementations."""

from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

REDACT_KEY_FRAGMENTS = (
    "password",
    "secret",
    "sshkey",
    "token",
    "preauth",
    "apikey",
    "privatekey",
)


def normalize_list(data: Any) -> list[dict[str, Any]]:
    """Coerce pfREST list-or-single-object payloads into a list of dicts."""
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def require_confirm(confirm: bool) -> None:
    """Reject mutating operations unless ``confirm`` is explicitly ``True``.

    Raises:
        ValueError: When ``confirm`` is not ``True``.
    """
    if confirm is not True:
        raise ValueError(
            "Mutating operation rejected: confirm must be true. " "Re-run with confirm=true after verifying the target."
        )


def parse_model(model: type[T], **kwargs: Any) -> T:
    """Validate tool input kwargs against a Pydantic model."""
    return model.model_validate(kwargs)


def redact_sensitive(data: Any) -> Any:
    """Redact values whose keys look like secrets before returning API payloads to agents."""
    if isinstance(data, dict):
        redacted: dict[str, Any] = {}
        for key, value in data.items():
            key_lower = key.lower()
            if any(fragment in key_lower for fragment in REDACT_KEY_FRAGMENTS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_sensitive(value)
        return redacted
    if isinstance(data, list):
        return [redact_sensitive(item) for item in data]
    return data


def firewall_has_anti_lockout(rules: list[dict[str, Any]]) -> bool:
    """Return True when a rule looks like pfSense's anti-lockout rule."""
    for rule in rules:
        blob = " ".join(str(rule.get(field, "")) for field in ("descr", "description", "name", "note", "type")).lower()
        if "anti-lockout" in blob or "anti lockout" in blob or "lockout rule" in blob:
            return True
    return False
