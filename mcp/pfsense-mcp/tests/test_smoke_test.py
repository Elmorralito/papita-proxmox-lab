"""Smoke test unit tests."""

from pfsense_mcp.tools.system import _interface_has_lan_cidr, _parse_tailscale_status, _tailscale_warnings


def test_parse_tailscale_advertised_routes() -> None:
    status = _parse_tailscale_status({"advertised_routes": ["172.16.0.0/16"]})
    assert status["advertised_routes"] == ["172.16.0.0/16"]


def test_tailscale_warning_missing_route() -> None:
    warnings = _tailscale_warnings({"advertised_routes": ["10.0.0.0/8"]})
    assert any("172.16.0.0/16" in w for w in warnings)


def test_interface_lan_cidr_detected() -> None:
    interfaces = [{"ipaddr": "172.16.0.1/24", "descr": "LAN"}]
    assert _interface_has_lan_cidr(interfaces) is True


def test_tool_registry_read_only() -> None:
    from pfsense_mcp.tools.registry import ToolClass

    assert ToolClass.DESTRUCTIVE.value == "destructive"


def test_redact_sensitive() -> None:
    from pfsense_mcp.tools.helpers import redact_sensitive

    payload = {"name": "lan", "preauthkey": "secret-value", "nested": {"apikey": "x"}}
    redacted = redact_sensitive(payload)
    assert redacted["preauthkey"] == "[REDACTED]"
    assert redacted["nested"]["apikey"] == "[REDACTED]"


def test_firewall_anti_lockout() -> None:
    from pfsense_mcp.tools.helpers import firewall_has_anti_lockout

    assert firewall_has_anti_lockout([{"descr": "Anti-Lockout Rule"}]) is True
    assert firewall_has_anti_lockout([{"descr": "Allow LAN"}]) is False
