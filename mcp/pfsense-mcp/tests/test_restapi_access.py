"""Tests for REST API access policy evaluation."""

from pfsense_mcp.policy.restapi_access import evaluate_restapi_access_policy


def test_restapi_access_empty_allowed_lan_host() -> None:
    report = evaluate_restapi_access_policy(
        {"allowed_interfaces": []},
        host="172.16.0.1",
        api_user="mcp-cursor-agent",
    )
    assert report["compliant"] is True
    assert report["issues"] == []


def test_restapi_access_lan_requires_lan_interface() -> None:
    report = evaluate_restapi_access_policy(
        {"allowed_interfaces": ["wan"]},
        host="172.16.0.1",
    )
    assert report["compliant"] is False
    assert any("allowed_interfaces" in issue for issue in report["issues"])


def test_restapi_access_tailscale_host_rejects_non_empty() -> None:
    report = evaluate_restapi_access_policy(
        {"allowed_interfaces": ["lan"]},
        host="100.64.0.1",
    )
    assert report["compliant"] is False
    assert any("Tailscale IP" in issue for issue in report["issues"])


def test_restapi_access_list_warns_missing_lan_allow() -> None:
    report = evaluate_restapi_access_policy(
        {
            "allowed_interfaces": [],
            "access_lists": [
                {
                    "type": "allow",
                    "network": "100.64.0.0/10",
                    "users": ["mcp-cursor-agent"],
                }
            ],
        },
        host="172.16.0.1",
        api_user="mcp-cursor-agent",
    )
    assert report["compliant"] is False
    assert any("172.16.0.0/16" in issue for issue in report["issues"])
