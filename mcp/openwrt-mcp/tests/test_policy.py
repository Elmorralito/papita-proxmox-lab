"""Canonical digest, template validation and plan building."""

import pytest

from openwrt_mcp.canonical import canonical_json, plan_digest
from openwrt_mcp.errors import InvalidInput, OperationProhibited, TargetLocked
from openwrt_mcp.policy.engine import build_plan
from owrt_testlib import load_fixture


def _plan(**kw):
    base = {
        "router_id": "openwrt-pi",
        "snapshot": load_fixture("inspect_ok.json"),
        "action": "upsert",
        "rule_id": "allow-alt",
        "fields": {"template": "allow_tcp_from_lan", "dest_port": 8080, "family": "ipv4"},
        "verify_deadline_sec": 120,
        "plan_ttl_sec": 900,
        "now": 1_000,
    }
    base.update(kw)
    return build_plan(**base)


def test_canonical_json_sorted_and_compact():
    assert canonical_json({"b": 1, "a": [True, "x/y"]}) == '{"a":[true,"x/y"],"b":1}'


@pytest.mark.parametrize("bad", ["a b", 'q"uote', "é", "a\nb"])
def test_canonical_rejects_unsafe_strings(bad):
    with pytest.raises(ValueError):
        canonical_json({"k": bad})


def test_canonical_rejects_float_and_none():
    for bad in (1.5, None):
        with pytest.raises(ValueError):
            canonical_json({"k": bad})


def test_digest_known_vector():
    # Same vector is asserted in the router agent test (tests/agent/run_agent_tests.sh).
    d = plan_digest(
        router_id="openwrt-pi",
        operations=[{"type": "firewall.rule.delete", "rule_id": "x"}],
        state_precondition="sha256:aa",
        policy_revision=1,
        recovery={"mode": "auto_revert", "deadline_s": 120},
    )
    assert d == plan_digest(
        router_id="openwrt-pi",
        operations=[{"rule_id": "x", "type": "firewall.rule.delete"}],
        state_precondition="sha256:aa",
        policy_revision=1,
        recovery={"deadline_s": 120, "mode": "auto_revert"},
    )
    assert d.startswith("sha256:") and len(d) == 71


def test_plan_upsert_has_diff_digest_and_expiry():
    draft = _plan()
    assert draft.diff == ["+ firewall.mcp_allow_alt: src=lan proto=tcp dest_port=8080 family=ipv4 target=ACCEPT"]
    assert draft.risk == "low" and draft.expires_at == 1_900
    assert draft.state_precondition.startswith("sha256:9f2c")
    assert _plan().digest == draft.digest  # deterministic


@pytest.mark.parametrize("port", [22, 53, 80, 443, 41641])
def test_prohibited_ports_denied(port):
    with pytest.raises(OperationProhibited):
        _plan(fields={"template": "allow_tcp_from_lan", "dest_port": port})


def test_src_ip_must_be_inside_lan():
    with pytest.raises(OperationProhibited):
        _plan(fields={"template": "allow_tcp_from_lan", "dest_port": 8080, "src_ip": "8.8.8.0/24"})
    ok = _plan(fields={"template": "allow_tcp_from_lan", "dest_port": 8080, "src_ip": "172.16.0.0/24"})
    assert "src_ip=172.16.0.0/24" in ok.diff[-1]


@pytest.mark.parametrize("extra", [{"target": "DROP"}, {"src": "wan"}, {"proto": "udp"}, {"shell_cmd": "id"}])
def test_unknown_or_unsafe_fields_rejected(extra):
    with pytest.raises((InvalidInput, OperationProhibited)):
        _plan(fields={"template": "allow_tcp_from_lan", "dest_port": 8080, **extra})


@pytest.mark.parametrize("rule_id", ["Bad", "../x", "a b", "", "x" * 40, "-x"])
def test_bad_rule_ids(rule_id):
    with pytest.raises(InvalidInput):
        _plan(rule_id=rule_id)


def test_delete_requires_owned_rule():
    with pytest.raises(InvalidInput):
        _plan(action="delete", rule_id="not-mine", fields=None)
    draft = _plan(action="delete", rule_id="allow-metrics", fields=None)
    assert draft.diff[0].startswith("- firewall.mcp_allow_metrics")


def test_noop_upsert_rejected():
    with pytest.raises(InvalidInput):
        _plan(rule_id="allow-metrics", fields={"template": "allow_tcp_from_lan", "dest_port": 9100})


def test_shared_pending_changes_and_active_txn_block_planning():
    snap = load_fixture("inspect_ok.json")
    with pytest.raises(TargetLocked):
        _plan(snapshot={**snap, "pending_changes": True})
    with pytest.raises(TargetLocked):
        _plan(snapshot={**snap, "active_txn": "plan_x"})
