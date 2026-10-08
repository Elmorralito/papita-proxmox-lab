"""Typed firewall operations and the single supported template (``allow_tcp_from_lan``)."""

import ipaddress
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from openwrt_mcp.constants import (
    DEFAULT_LAN_CIDR,
    PROHIBITED_PORTS,
    RULE_ID_PATTERN,
    RULE_PREFIX,
    SUPPORTED_TEMPLATES,
    TEMPLATE_ALLOW_TCP_FROM_LAN,
)
from openwrt_mcp.errors import InvalidInput, OperationProhibited

_LAN_NET = ipaddress.ip_network(DEFAULT_LAN_CIDR)


def validate_rule_id(rule_id: str) -> str:
    """Return ``rule_id`` if it matches the allowed pattern."""
    if not isinstance(rule_id, str) or not re.match(RULE_ID_PATTERN, rule_id):
        raise InvalidInput("rule_id must match " + RULE_ID_PATTERN)
    return rule_id


def section_name(rule_id: str) -> str:
    """UCI section name for an agent-owned rule."""
    return RULE_PREFIX + validate_rule_id(rule_id).replace("-", "_")


class AllowTcpFromLan(BaseModel):
    """Fields of the ``allow_tcp_from_lan`` template. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    template: Literal["allow_tcp_from_lan"] = "allow_tcp_from_lan"
    src: Literal["lan"] = "lan"
    proto: Literal["tcp"] = "tcp"
    dest_port: int = Field(ge=1, le=65535)
    family: Literal["ipv4", "ipv6", "any"] = "ipv4"
    src_ip: str | None = None

    @field_validator("dest_port")
    @classmethod
    def _port(cls, value: int) -> int:
        """Reject prohibited management/DNS/VPN ports."""
        if value in PROHIBITED_PORTS:
            raise OperationProhibited(f"port {value} is prohibited (management/DNS/VPN)")
        return value

    @field_validator("src_ip")
    @classmethod
    def _src_ip(cls, value: str | None) -> str | None:
        """Validate that the source IP is a valid address."""
        if value is None:
            return None
        try:
            net = ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise InvalidInput("src_ip must be an IPv4 CIDR or address") from exc
        if net.version != 4 or not net.subnet_of(_LAN_NET):  # type: ignore[arg-type]
            raise OperationProhibited(f"src_ip must be inside {DEFAULT_LAN_CIDR}")
        return str(net)

    def to_dict(self) -> dict[str, Any]:
        """Canonical-JSON-safe dict (``None`` omitted)."""
        data = self.model_dump()
        if data["src_ip"] is None:
            del data["src_ip"]
        return data


def build_upsert(rule_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Validate and return a ``firewall.rule.upsert`` operation dict."""
    validate_rule_id(rule_id)
    if fields.get("template", TEMPLATE_ALLOW_TCP_FROM_LAN) not in SUPPORTED_TEMPLATES:
        raise InvalidInput("unsupported template; supported: " + ", ".join(SUPPORTED_TEMPLATES))
    model = AllowTcpFromLan.model_validate(fields)
    return {"type": "firewall.rule.upsert", "rule_id": rule_id, "fields": model.to_dict()}


def build_delete(rule_id: str) -> dict[str, Any]:
    """Return a ``firewall.rule.delete`` operation dict."""
    validate_rule_id(rule_id)
    return {"type": "firewall.rule.delete", "rule_id": rule_id}


def render_rule_line(rule_id: str, fields: dict[str, Any]) -> str:
    """Human-readable diff line for a rule (target is always ACCEPT)."""
    parts = [f"src={fields['src']}", f"proto={fields['proto']}", f"dest_port={fields['dest_port']}"]
    parts.append(f"family={fields['family']}")
    if "src_ip" in fields:
        parts.append(f"src_ip={fields['src_ip']}")
    parts.append("target=ACCEPT")
    return f"firewall.{section_name(rule_id)}: " + " ".join(parts)
