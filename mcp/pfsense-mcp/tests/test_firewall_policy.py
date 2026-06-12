"""Tests for Tailscale-tab firewall policy planning and verification."""

from pfsense_mcp.firewall_policy import (
    DESCR_GATEWAY,
    DESCR_LAN,
    DESCR_SELF,
    evaluate_tailscale_firewall_policy,
    plan_tailscale_firewall_changes,
)


def _compliant_rules() -> list[dict]:
    return [
        {
            "id": 2,
            "type": "pass",
            "interface": ["Tailscale"],
            "source": "AUTH_CLIENTS",
            "destination": "(self)",
            "protocol": "tcp",
            "descr": DESCR_SELF,
            "disabled": False,
        },
        {
            "id": 3,
            "type": "pass",
            "interface": ["Tailscale"],
            "source": "AUTH_CLIENTS",
            "destination": "172.16.0.1",
            "protocol": "tcp",
            "descr": DESCR_GATEWAY,
            "disabled": False,
        },
        {
            "id": 4,
            "type": "pass",
            "interface": ["Tailscale"],
            "source": "AUTH_CLIENTS",
            "destination": "172.16.0.0/16",
            "protocol": None,
            "descr": DESCR_LAN,
            "disabled": False,
        },
    ]


def test_evaluate_compliant_policy() -> None:
    report = evaluate_tailscale_firewall_policy(_compliant_rules())
    assert report["compliant"] is True
    assert not report["issues"]
    assert report["planned_changes"] == 0


def test_evaluate_missing_gateway() -> None:
    rules = [rule for rule in _compliant_rules() if rule["id"] != 3]
    report = evaluate_tailscale_firewall_policy(rules)
    assert report["compliant"] is False
    assert any("gateway" in issue for issue in report["issues"])
    assert plan_tailscale_firewall_changes(rules)


def test_plan_merge_legacy_self_rules() -> None:
    rules = [
        {
            "id": 2,
            "type": "pass",
            "interface": ["Tailscale"],
            "source": "AUTH_CLIENTS",
            "destination": "(self)",
            "protocol": "tcp",
            "destination_port": "443",
            "descr": "old 443",
            "disabled": False,
        },
        {
            "id": 3,
            "type": "pass",
            "interface": ["Tailscale"],
            "source": "AUTH_CLIENTS",
            "destination": "(self)",
            "protocol": "tcp",
            "destination_port": "80",
            "descr": "old 80",
            "disabled": False,
        },
        {
            "id": 4,
            "type": "pass",
            "interface": ["Tailscale"],
            "source": "AUTH_CLIENTS",
            "destination": "(self)",
            "protocol": "tcp",
            "destination_port": "22",
            "descr": "old 22",
            "disabled": False,
        },
        {
            "id": 5,
            "type": "pass",
            "interface": ["Tailscale"],
            "source": "AUTH_CLIENTS",
            "destination": "vtnet1",
            "protocol": None,
            "descr": "Temp LAN",
            "disabled": False,
        },
    ]
    changes = plan_tailscale_firewall_changes(rules)
    kinds = [change["kind"] for change in changes]
    assert "self" in kinds
    assert "gateway" in kinds
    assert "lan" in kinds
    assert any(change["action"] == "delete" for change in changes)


def test_smoke_core_passed_optional_tailscale_route() -> None:
    from pfsense_mcp.tools.smoke_test import smoke_core_passed

    report = {
        "tests": [
            {"name": "api_key_valid", "status": "pass"},
            {"name": "tailscale_subnet_route", "status": "fail"},
            {"name": "tailscale_firewall_policy", "status": "pass"},
        ]
    }
    assert smoke_core_passed(report) is True

    report["tests"][2]["status"] = "fail"
    assert smoke_core_passed(report) is False
