"""Unit tests for TrueNAS smoke test helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from truenas_mcp.config import TnasSettings
from truenas_mcp.tools.smoke_test import (
    CORE_SMOKE_CHECKS,
    _check_config_valid,
    _tool_response_ok,
    run_smoke_tests,
    smoke_core_passed,
)


def test_tool_response_ok() -> None:
    assert _tool_response_ok('{"ok": true, "data": {}}')
    assert not _tool_response_ok('{"ok": false, "error": {}}')


def test_smoke_core_passed_requires_core_checks() -> None:
    report = {
        "tests": [
            {"name": "config_valid", "status": "pass"},
            {"name": "websocket_auth", "status": "pass"},
            {"name": "system_info", "status": "pass"},
            {"name": "pools_query", "status": "pass"},
            {"name": "lab_ha_pool", "status": "warn"},
        ]
    }
    assert smoke_core_passed(report)
    assert CORE_SMOKE_CHECKS == {"config_valid", "websocket_auth", "system_info", "pools_query"}


def test_smoke_core_failed_when_auth_fails() -> None:
    report = {
        "tests": [
            {"name": "config_valid", "status": "pass"},
            {"name": "websocket_auth", "status": "fail"},
        ]
    }
    assert not smoke_core_passed(report)


def test_check_config_valid() -> None:
    settings = TnasSettings(host="172.16.0.100", api_key="test-key")
    assert _check_config_valid(settings)["status"] == "pass"


@pytest.mark.asyncio
async def test_run_smoke_tests_stops_after_auth_failure() -> None:
    settings = TnasSettings(host="172.16.0.100", api_key="test-key")
    client = AsyncMock()
    client.call.side_effect = RuntimeError("auth failed")

    with (
        patch("truenas_mcp.tools.smoke_test.get_settings", return_value=settings),
        patch("truenas_mcp.tools.smoke_test.get_client", return_value=client),
    ):
        report = await run_smoke_tests()

    names = [item["name"] for item in report["tests"]]
    assert names == ["config_valid", "websocket_auth"]
    assert not report["core_passed"]


@pytest.mark.asyncio
async def test_run_smoke_tests_basic_success() -> None:
    settings = TnasSettings(host="172.16.0.100", api_key="test-key")

    async def fake_call(method: str, params: list[Any] | None = None) -> Any:
        if method == "system.state":
            return "READY"
        if method == "system.info":
            return {"hostname": "nas", "version": "25.10.0"}
        if method == "pool.query":
            return [{"name": "pve-cluster-oldtimers-ha-storage", "status": "ONLINE"}]
        if method == "alert.list":
            return []
        if method == "sharing.nfs.query":
            return [{"enabled": True, "path": "/mnt/pve-cluster-oldtimers-ha-storage/pve-nfs"}]
        if method == "pool.dataset.query":
            return [{"name": "tank/data"}]
        if method == "disk.query":
            return [{"devname": "sda"}]
        if method == "core.get_jobs":
            return []
        if method == "pool.scrub.query":
            return [{"id": 1}]
        if method == "smart.test.results":
            return []
        if method == "alert.list_policies":
            return [{"id": 1, "policy": "IMMEDIATELY"}]
        if method == "app.query":
            return [{"name": "scrutiny", "id": "scrutiny", "state": "RUNNING"}]
        raise AssertionError(f"unexpected method {method}")

    client = AsyncMock()
    client.call.side_effect = fake_call

    with (
        patch("truenas_mcp.tools.smoke_test.get_settings", return_value=settings),
        patch("truenas_mcp.tools.smoke_test.get_client", return_value=client),
    ):
        report = await run_smoke_tests()

    assert report["core_passed"]
    assert report["passed"] >= 14
    names = {item["name"] for item in report["tests"]}
    assert "datasets_query" in names
    assert "scrutiny_app_running" in names
