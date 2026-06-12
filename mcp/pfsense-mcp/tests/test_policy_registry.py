"""Tests for policy registry and API endpoint probes."""

from unittest.mock import AsyncMock

import pytest

from pfsense_mcp.policy.api_endpoints import evaluate_api_endpoints_policy
from pfsense_mcp.policy.registry import policy_smoke_checks, verify_all_policies


@pytest.mark.asyncio
async def test_api_endpoints_all_ok() -> None:
    client = AsyncMock()
    client.get = AsyncMock(return_value={"data": []})
    report = await evaluate_api_endpoints_policy(client)
    assert report["compliant"] is True
    assert client.get.await_count == 6


@pytest.mark.asyncio
async def test_api_endpoints_403_fails() -> None:
    from pfsense_mcp.client.errors import PfsApiError

    client = AsyncMock()

    async def _get(path: str, params=None):  # noqa: ANN001
        if path == "/firewall/rules":
            raise PfsApiError("forbidden", status_code=403)
        return {}

    client.get = _get
    report = await evaluate_api_endpoints_policy(client)
    assert report["compliant"] is False
    assert any("403" in issue for issue in report["issues"])


@pytest.mark.asyncio
async def test_verify_all_policies_smoke_rows() -> None:
    from pfsense_mcp.firewall_policy import DESCR_GATEWAY, DESCR_LAN, DESCR_SELF

    rules = [
        {
            "id": 1,
            "type": "pass",
            "interface": ["Tailscale"],
            "source": "AUTH_CLIENTS",
            "destination": "(self)",
            "protocol": "tcp",
            "descr": DESCR_SELF,
            "disabled": False,
        },
        {
            "id": 2,
            "type": "pass",
            "interface": ["Tailscale"],
            "source": "AUTH_CLIENTS",
            "destination": "172.16.0.1",
            "protocol": "tcp",
            "descr": DESCR_GATEWAY,
            "disabled": False,
        },
        {
            "id": 3,
            "type": "pass",
            "interface": ["Tailscale"],
            "source": "AUTH_CLIENTS",
            "destination": "172.16.0.0/16",
            "protocol": None,
            "descr": DESCR_LAN,
            "disabled": False,
        },
    ]
    client = AsyncMock()
    client.get = AsyncMock(
        side_effect=[
            rules,
            {"allowed_interfaces": []},
            {},
            {},
            {},
            {},
            {},
            {},
        ]
    )
    from pfsense_mcp.config import PfsSettings

    settings = PfsSettings(
        host="172.16.0.1",
        api_key="test-key",
    )
    suite = await verify_all_policies(client, settings=settings)
    rows = policy_smoke_checks(suite)
    names = {row["name"] for row in rows}
    assert names == {
        "tailscale_firewall_policy",
        "restapi_access_policy",
        "api_endpoints_policy",
    }
    assert all(row["status"] == "pass" for row in rows)
