"""Tests for helper utilities."""

from truenas_mcp.tools.helpers import (
    critical_alerts,
    dataset_capacity_warnings,
    dataset_used_ratio,
    pool_health_warnings,
)


def test_pool_health_warnings_degraded() -> None:
    warnings = pool_health_warnings([{"name": "tank", "status": "DEGRADED"}])
    assert len(warnings) == 1
    assert "DEGRADED" in warnings[0]


def test_dataset_used_ratio_from_parsed_bytes() -> None:
    assert dataset_used_ratio(
        {"used": {"parsed": 90}, "available": {"parsed": 10}}
    ) == 0.9
    assert dataset_used_ratio(
        {"used": {"parsed": 100}, "available": {"parsed": 0}}
    ) == 1.0
    assert dataset_used_ratio({"used": {"parsed": "n/a"}}) is None


def test_dataset_capacity_warnings_at_threshold() -> None:
    datasets = [
        {"name": "tank/full", "used": {"parsed": 95}, "available": {"parsed": 5}},
        {"name": "tank/ok", "used": {"parsed": 50}, "available": {"parsed": 50}},
    ]
    warnings = dataset_capacity_warnings(datasets)
    assert len(warnings) == 1
    assert "tank/full" in warnings[0]


def test_critical_alerts_filters_levels() -> None:
    alerts = [
        {"level": "INFO", "message": "ok"},
        {"level": "CRITICAL", "message": "bad"},
    ]
    result = critical_alerts(alerts)
    assert len(result) == 1
    assert result[0]["level"] == "CRITICAL"
