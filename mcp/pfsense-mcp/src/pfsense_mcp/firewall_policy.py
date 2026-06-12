"""Tailscale-tab firewall policy: plan, apply, and verify AUTH_CLIENTS rules."""

from __future__ import annotations

from typing import Any

from pfsense_mcp.client.http import PfsClient
from pfsense_mcp.constants import (
    EP_FIREWALL_APPLY,
    EP_FIREWALL_RULE,
    EP_FIREWALL_RULES,
    LAB_LAN_CIDR,
    LAB_PFSENSE_LAN_IP,
)

DESCR_SELF = "AUTH_CLIENTS → pfSense (SSH, WebGUI, pfREST)"
DESCR_GATEWAY = "AUTH_CLIENTS → pfSense LAN IP (172.16.0.1)"
DESCR_LAN = "AUTH_CLIENTS → lab LAN (172.16.0.0/16)"

POLICY_RULE_KINDS = ("self", "gateway", "lan")


def interface_names(rule: dict[str, Any]) -> list[str]:
    """Return interface name(s) from a pfSense firewall rule payload."""
    raw = rule.get("interface") or []
    if isinstance(raw, str):
        return [raw]
    return [str(item) for item in raw]


def is_tailscale_rule(rule: dict[str, Any]) -> bool:
    """Return whether the rule is bound to the Tailscale interface."""
    return any(name.lower() == "tailscale" for name in interface_names(rule))


def is_auth_clients_rule(rule: dict[str, Any]) -> bool:
    """Return whether the rule source alias is ``AUTH_CLIENTS`` (tailnet clients)."""
    return str(rule.get("source", "")).upper() == "AUTH_CLIENTS"


def lan_destinations(lan_cidr: str, lan_gateway: str) -> frozenset[str]:
    """Return destination tokens that qualify as lab-LAN targets in policy checks."""
    return frozenset({lan_cidr, "vtnet1", "lan", lan_gateway, f"{lan_gateway}/32"})


def classify_tailscale_auth_rules(
    rules: list[dict[str, Any]],
    *,
    lan_cidr: str = LAB_LAN_CIDR,
    lan_gateway: str = LAB_PFSENSE_LAN_IP,
) -> dict[str, list[dict[str, Any]]]:
    """Group enabled AUTH_CLIENTS rules on the Tailscale interface by policy role."""
    tailscale_auth = [
        rule for rule in rules if is_tailscale_rule(rule) and is_auth_clients_rule(rule) and not rule.get("disabled")
    ]
    tailscale_auth.sort(key=lambda item: int(item.get("id", 0)))

    lan_dests = lan_destinations(lan_cidr, lan_gateway)
    return {
        "all": tailscale_auth,
        "self": [rule for rule in tailscale_auth if rule.get("destination") == "(self)"],
        "gateway": [
            rule for rule in tailscale_auth if str(rule.get("destination", "")) in {lan_gateway, f"{lan_gateway}/32"}
        ],
        "lan": [
            rule
            for rule in tailscale_auth
            if str(rule.get("destination", "")) in lan_dests
            and str(rule.get("destination", "")) not in {lan_gateway, f"{lan_gateway}/32"}
        ],
    }


def _self_rule_compliant(rule: dict[str, Any]) -> bool:
    """Return True when a firewall rule matches the agreed Tailscale self rule."""
    return (
        rule.get("type") == "pass"
        and rule.get("destination") == "(self)"
        and rule.get("protocol") == "tcp"
        and rule.get("descr") == DESCR_SELF
    )


def _gateway_rule_compliant(rule: dict[str, Any], lan_gateway: str) -> bool:
    """Return True when a firewall rule matches the agreed LAN gateway rule."""
    return (
        rule.get("type") == "pass"
        and str(rule.get("destination")) == lan_gateway
        and rule.get("protocol") == "tcp"
        and rule.get("descr") == DESCR_GATEWAY
    )


def _lan_rule_compliant(rule: dict[str, Any], lan_cidr: str) -> bool:
    """Return True when a firewall rule matches the agreed LAN subnet rule."""
    return (
        rule.get("type") == "pass"
        and str(rule.get("destination")) in {lan_cidr, "vtnet1"}
        and rule.get("descr") == DESCR_LAN
    )


def evaluate_tailscale_firewall_policy(
    rules: list[dict[str, Any]],
    *,
    lan_cidr: str = LAB_LAN_CIDR,
    lan_gateway: str = LAB_PFSENSE_LAN_IP,
) -> dict[str, Any]:
    """Return compliance report for the agreed AUTH_CLIENTS Tailscale-tab layout."""
    grouped = classify_tailscale_auth_rules(rules, lan_cidr=lan_cidr, lan_gateway=lan_gateway)
    issues: list[str] = []

    self_rules = grouped["self"]
    gateway_rules = grouped["gateway"]
    lan_rules = grouped["lan"]

    if not self_rules:
        issues.append(f"missing self rule: {DESCR_SELF}")
    elif not _self_rule_compliant(self_rules[0]):
        issues.append(f"self rule id={self_rules[0].get('id')} does not match policy")
    if len(self_rules) > 1:
        issues.append(f"duplicate self rules: {[rule.get('id') for rule in self_rules[1:]]}")

    if not gateway_rules:
        issues.append(f"missing gateway rule: {DESCR_GATEWAY}")
    elif not _gateway_rule_compliant(gateway_rules[0], lan_gateway):
        issues.append(f"gateway rule id={gateway_rules[0].get('id')} does not match policy")
    if len(gateway_rules) > 1:
        issues.append(f"duplicate gateway rules: {[rule.get('id') for rule in gateway_rules[1:]]}")

    if not lan_rules:
        issues.append(f"missing LAN rule: {DESCR_LAN}")
    elif not _lan_rule_compliant(lan_rules[0], lan_cidr):
        issues.append(f"LAN rule id={lan_rules[0].get('id')} does not match policy")
    if len(lan_rules) > 1:
        issues.append(f"duplicate LAN rules: {[rule.get('id') for rule in lan_rules[1:]]}")

    expected_ids = {rule.get("id") for bucket in (self_rules[:1], gateway_rules[:1], lan_rules[:1]) for rule in bucket}
    extras = [rule for rule in grouped["all"] if rule.get("id") not in expected_ids]
    if extras:
        issues.append(
            "unexpected AUTH_CLIENTS Tailscale rules: "
            + ", ".join(f"id={rule.get('id')} descr={rule.get('descr')!r}" for rule in extras)
        )

    planned = plan_tailscale_firewall_changes(rules, lan_cidr=lan_cidr, lan_gateway=lan_gateway)
    return {
        "compliant": not issues and not planned,
        "issues": issues,
        "planned_changes": len(planned),
        "rules": {
            "self": self_rules[:1],
            "gateway": gateway_rules[:1],
            "lan": lan_rules[:1],
        },
    }


def plan_tailscale_firewall_changes(
    rules: list[dict[str, Any]],
    *,
    lan_cidr: str = LAB_LAN_CIDR,
    lan_gateway: str = LAB_PFSENSE_LAN_IP,
) -> list[dict[str, Any]]:
    """Return pfREST mutations needed to converge on the agreed Tailscale-tab policy."""
    grouped = classify_tailscale_auth_rules(rules, lan_cidr=lan_cidr, lan_gateway=lan_gateway)
    self_rules = grouped["self"]
    gateway_rules = grouped["gateway"]
    lan_rules = grouped["lan"]

    changes: list[dict[str, Any]] = []
    delete_ids: set[int] = set()
    spare_self_id: int | None = None

    if not self_rules:
        changes.append(
            {
                "action": "create",
                "kind": "self",
                "body": {
                    "type": "pass",
                    "interface": ["Tailscale"],
                    "ipprotocol": "inet46",
                    "protocol": "tcp",
                    "source": "AUTH_CLIENTS",
                    "destination": "(self)",
                    "destination_port": None,
                    "descr": DESCR_SELF,
                    "log": True,
                },
            }
        )
    else:
        primary = self_rules[0]
        spare_self_id = int(self_rules[1]["id"]) if len(self_rules) > 1 else None
        if not _self_rule_compliant(primary) or primary.get("destination_port") not in (None, "", "443"):
            changes.append(
                {
                    "action": "patch",
                    "id": primary["id"],
                    "kind": "self",
                    "body": {
                        "destination_port": None,
                        "descr": DESCR_SELF,
                        "protocol": "tcp",
                    },
                }
            )
        for duplicate in self_rules[2:]:
            delete_ids.add(int(duplicate["id"]))

    if not gateway_rules:
        if spare_self_id is not None:
            changes.append(
                {
                    "action": "patch",
                    "id": spare_self_id,
                    "kind": "gateway",
                    "body": {
                        "destination": lan_gateway,
                        "destination_port": None,
                        "protocol": "tcp",
                        "ipprotocol": "inet",
                        "descr": DESCR_GATEWAY,
                    },
                }
            )
            delete_ids.discard(spare_self_id)
        else:
            changes.append(
                {
                    "action": "create",
                    "kind": "gateway",
                    "body": {
                        "type": "pass",
                        "interface": ["Tailscale"],
                        "ipprotocol": "inet",
                        "protocol": "tcp",
                        "source": "AUTH_CLIENTS",
                        "destination": lan_gateway,
                        "destination_port": None,
                        "descr": DESCR_GATEWAY,
                        "log": True,
                    },
                }
            )
    else:
        primary_gateway = gateway_rules[0]
        if spare_self_id is not None and int(primary_gateway["id"]) != spare_self_id:
            delete_ids.add(spare_self_id)
        if not _gateway_rule_compliant(primary_gateway, lan_gateway):
            changes.append(
                {
                    "action": "patch",
                    "id": primary_gateway["id"],
                    "kind": "gateway",
                    "body": {
                        "destination": lan_gateway,
                        "destination_port": None,
                        "protocol": "tcp",
                        "ipprotocol": "inet",
                        "descr": DESCR_GATEWAY,
                    },
                }
            )
        for duplicate in gateway_rules[1:]:
            delete_ids.add(int(duplicate["id"]))

    if not lan_rules:
        changes.append(
            {
                "action": "create",
                "kind": "lan",
                "body": {
                    "type": "pass",
                    "interface": ["Tailscale"],
                    "ipprotocol": "inet",
                    "protocol": None,
                    "source": "AUTH_CLIENTS",
                    "destination": lan_cidr,
                    "descr": DESCR_LAN,
                    "log": True,
                },
            }
        )
    else:
        primary_lan = lan_rules[0]
        if not _lan_rule_compliant(primary_lan, lan_cidr):
            changes.append(
                {
                    "action": "patch",
                    "id": primary_lan["id"],
                    "kind": "lan",
                    "body": {
                        "destination": lan_cidr,
                        "descr": DESCR_LAN,
                        "ipprotocol": "inet",
                    },
                }
            )
        for duplicate in lan_rules[1:]:
            delete_ids.add(int(duplicate["id"]))

    if spare_self_id is not None and not any(
        change.get("id") == spare_self_id and change["action"] == "patch" for change in changes
    ):
        delete_ids.add(spare_self_id)

    for rule_id in sorted(delete_ids):
        changes.append({"action": "delete", "id": rule_id, "kind": "duplicate"})

    return changes


async def fetch_firewall_rules(client: PfsClient) -> list[dict[str, Any]]:
    """Fetch up to 200 firewall rules from pfREST."""
    rules = await client.get(EP_FIREWALL_RULES, params={"limit": 200})
    if not isinstance(rules, list):
        raise RuntimeError("Unexpected firewall rules response")
    return rules


async def verify_tailscale_firewall_policy(client: PfsClient) -> dict[str, Any]:
    """Fetch live rules and evaluate Tailscale-tab ``AUTH_CLIENTS`` compliance."""
    rules = await fetch_firewall_rules(client)
    return evaluate_tailscale_firewall_policy(rules)


async def _patch_rule(client: PfsClient, rule_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """PATCH an existing firewall rule via pfREST."""
    return await client.patch(EP_FIREWALL_RULE, json_body={"id": rule_id, **body})


async def _delete_rule(client: PfsClient, rule_id: int) -> dict[str, Any]:
    """DELETE a firewall rule via pfREST."""
    return await client.delete(EP_FIREWALL_RULE, json_body={"id": rule_id})


async def _create_rule(client: PfsClient, body: dict[str, Any]) -> dict[str, Any]:
    """POST a new firewall rule via pfREST."""
    return await client.post(EP_FIREWALL_RULE, json_body=body)


async def _apply_firewall(client: PfsClient) -> dict[str, Any]:
    """Apply pending firewall configuration changes on pfSense."""
    return await client.post(EP_FIREWALL_APPLY, json_body={})


async def apply_tailscale_firewall_rules(
    client: PfsClient,
    *,
    lan_cidr: str = LAB_LAN_CIDR,
    lan_gateway: str = LAB_PFSENSE_LAN_IP,
    dry_run: bool = False,
    run_smoke: bool = True,
) -> dict[str, Any]:
    """Converge Tailscale-tab rules; optionally run MCP smoke tests after a live apply."""
    rules = await fetch_firewall_rules(client)
    changes = plan_tailscale_firewall_changes(rules, lan_cidr=lan_cidr, lan_gateway=lan_gateway)
    grouped = classify_tailscale_auth_rules(rules, lan_cidr=lan_cidr, lan_gateway=lan_gateway)

    if dry_run:
        return {
            "dry_run": True,
            "changes": changes,
            "rules_before": len(grouped["all"]),
            "policy_before": evaluate_tailscale_firewall_policy(rules, lan_cidr=lan_cidr, lan_gateway=lan_gateway),
        }

    applied: list[dict[str, Any]] = []
    for change in changes:
        action = change["action"]
        if action == "patch":
            patch_result = await _patch_rule(client, int(change["id"]), change["body"])
            applied.append({"action": action, "id": change["id"], "kind": change["kind"], "result": patch_result})
        elif action == "delete":
            delete_result = await _delete_rule(client, int(change["id"]))
            applied.append({"action": action, "id": change["id"], "kind": change["kind"], "result": delete_result})
        elif action == "create":
            create_result = await _create_rule(client, change["body"])
            applied.append({"action": action, "kind": change["kind"], "result": create_result})
        else:
            raise RuntimeError(f"Unknown change action: {action}")

    apply_result = await _apply_firewall(client) if applied else {"skipped": "no changes"}
    firewall_changed = bool(applied)

    updated_rules = await fetch_firewall_rules(client)
    policy_after = evaluate_tailscale_firewall_policy(
        updated_rules,
        lan_cidr=lan_cidr,
        lan_gateway=lan_gateway,
    )

    result: dict[str, Any] = {
        "dry_run": False,
        "changes": changes,
        "applied": applied,
        "firewall_apply": apply_result,
        "firewall_changed": firewall_changed,
        "policy_after": policy_after,
    }

    if run_smoke and firewall_changed:
        from pfsense_mcp.config import PfsSettings
        from pfsense_mcp.tools.smoke_test import run_post_firewall_smoke_tests

        settings = PfsSettings()
        smoke_report = await run_post_firewall_smoke_tests(client=client, settings=settings)
        result["smoke_test"] = smoke_report

    return result
