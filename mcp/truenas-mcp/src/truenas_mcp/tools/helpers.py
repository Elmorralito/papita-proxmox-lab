"""Shared helpers for TrueNAS MCP tools."""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

SENSITIVE_KEYS = frozenset({"password", "token", "api_key", "secret", "privatekey"})


def parse_model(model: type[T], **kwargs: Any) -> T:
    """Validate tool kwargs with a Pydantic model."""
    return model.model_validate(kwargs)


def require_confirm(confirm: bool) -> None:
    """Reject mutating operations unless confirm is explicitly true."""
    if confirm is not True:
        raise ValueError(
            "Mutating operation rejected: confirm must be true. " "Re-run with confirm=true after verifying the target."
        )


def normalize_list(data: Any) -> list[dict[str, Any]]:
    """Coerce API list payloads into a list of dicts."""
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("data", "results", "items"):
            inner = data.get(key)
            if isinstance(inner, list):
                return [item for item in inner if isinstance(item, dict)]
    return []


def redact_sensitive(value: Any) -> Any:
    """Recursively redact sensitive keys from nested dict/list structures."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


def _parsed_bytes(prop: Any) -> int | None:
    """Return a non-negative byte count from a TrueNAS property object."""
    if not isinstance(prop, dict):
        return None
    parsed = prop.get("parsed")
    if not isinstance(parsed, (int, float)) or parsed < 0:
        return None
    return int(parsed)


def dataset_used_ratio(dataset: dict[str, Any]) -> float | None:
    """Return used/(used+available) for a dataset, or None when unknown."""
    used = _parsed_bytes(dataset.get("used"))
    available = _parsed_bytes(dataset.get("available"))
    if used is None or available is None:
        return None
    total = used + available
    if total <= 0:
        return None
    return used / total


def dataset_capacity_warnings(datasets: list[dict[str, Any]], *, threshold: float = 0.9) -> list[str]:
    """Return warnings when any dataset is at or above the capacity threshold."""
    warnings: list[str] = []
    pct = int(threshold * 100)
    for dataset in datasets:
        ratio = dataset_used_ratio(dataset)
        if ratio is not None and ratio >= threshold:
            warnings.append(f"Dataset {dataset.get('name')} is >={pct}% full")
    return warnings


def pool_health_warnings(pools: list[dict[str, Any]]) -> list[str]:
    """Return warnings when any pool is not ONLINE."""
    warnings: list[str] = []
    for pool in pools:
        name = pool.get("name", "?")
        status = str(pool.get("status", "")).upper()
        if status and status != "ONLINE":
            warnings.append(f"Pool {name} status is {status}")
    return warnings


def critical_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter alerts to WARNING/CRITICAL levels."""
    critical: list[dict[str, Any]] = []
    for alert in alerts:
        level = str(alert.get("level", "")).upper()
        if level in {"WARNING", "CRITICAL", "ALERT"}:
            critical.append(alert)
    return critical
