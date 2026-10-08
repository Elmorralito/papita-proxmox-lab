"""Environment-backed settings (``OPENWRT_*``)."""

import ipaddress
import re
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from openwrt_mcp.constants import (
    DEFAULT_PLAN_TTL_SEC,
    DEFAULT_PROBE_HOST,
    DEFAULT_ROUTER_ID,
    DEFAULT_ROUTER_LAN_IP,
    DEFAULT_SSH_TIMEOUT_SEC,
    DEFAULT_VERIFY_DEADLINE_SEC,
    MAX_VERIFY_DEADLINE_SEC,
    ROUTER_ID_PATTERN,
)
from openwrt_mcp.logging_config import resolve_log_level


class OpenwrtSettings(BaseSettings):
    """Load ``OPENWRT_*`` settings from the environment or ``.env``."""

    model_config = SettingsConfigDict(env_prefix="OPENWRT_", extra="ignore")

    router_id: str = Field(default=DEFAULT_ROUTER_ID)
    host: str = Field(description="Router management IP literal (Tailscale IP recommended)")
    lan_host: str = Field(default=DEFAULT_ROUTER_LAN_IP, description="Router LAN IP used by LAN-vantage probes")
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_user: str = Field(default="root")
    ssh_key_path: Path = Field(description="Dedicated restricted agent key (NOT the root admin key)")
    known_hosts_path: Path = Field(description="Pinned known_hosts file containing only the router host key")
    ssh_timeout_sec: float = Field(default=DEFAULT_SSH_TIMEOUT_SEC, ge=2.0, le=300.0)

    state_dir: Path = Field(default=Path("~/.local/state/openwrt-mcp"))
    approver_key_path: Path = Field(default=Path("~/.config/openwrt-mcp/approver.key"))
    approver_pubkey_path: Path = Field(default=Path("~/.config/openwrt-mcp/approver.pub"))

    plan_ttl_sec: int = Field(default=DEFAULT_PLAN_TTL_SEC, ge=60, le=3600)
    verify_deadline_sec: int = Field(default=DEFAULT_VERIFY_DEADLINE_SEC, ge=30, le=MAX_VERIFY_DEADLINE_SEC)

    probe_host: str = Field(default=DEFAULT_PROBE_HOST, description="LAN-vantage host (PVE main node); '' disables")
    probe_user: str = Field(default="root")
    probe_key_path: Path | None = Field(default=None)
    probe_known_hosts_path: Path | None = Field(default=None)

    log_level: str = Field(default="INFO")

    @field_validator("router_id")
    @classmethod
    def _router_id(cls, value: str) -> str:
        """Validate the router identifier format."""
        if not re.match(ROUTER_ID_PATTERN, value):
            raise ValueError("OPENWRT_ROUTER_ID must match " + ROUTER_ID_PATTERN)
        return value

    @field_validator("host", "lan_host")
    @classmethod
    def _ip_literal(cls, value: str) -> str:
        """Require an IP literal (no hostnames)."""
        cleaned = value.strip()
        try:
            ipaddress.ip_address(cleaned)
        except ValueError as exc:
            raise ValueError("must be an IPv4/IPv6 literal (no hostnames)") from exc
        return cleaned

    @field_validator("probe_host")
    @classmethod
    def _probe_host(cls, value: str) -> str:
        """Allow an empty probe host or an IP literal."""
        cleaned = value.strip()
        if cleaned:
            ipaddress.ip_address(cleaned)
        return cleaned

    @field_validator("ssh_user", "probe_user")
    @classmethod
    def _user(cls, value: str) -> str:
        """Validate the probe SSH user name."""
        if not re.match(r"^[a-z_][a-z0-9_-]{0,31}$", value):
            raise ValueError("invalid user name")
        return value

    @field_validator("log_level")
    @classmethod
    def _log_level(cls, value: str) -> str:
        """Normalize and validate the log level."""
        resolve_log_level(value)
        return value.strip().upper()

    @model_validator(mode="after")
    def _expand_paths(self) -> "OpenwrtSettings":
        """Expand ``~`` in configured paths."""
        for name in (
            "ssh_key_path",
            "known_hosts_path",
            "state_dir",
            "approver_key_path",
            "approver_pubkey_path",
            "probe_key_path",
            "probe_known_hosts_path",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, Path(value).expanduser())
        return self

    @property
    def db_path(self) -> Path:
        """SQLite store path."""
        return self.state_dir / "state.sqlite3"

    @property
    def audit_path(self) -> Path:
        """Hash-chained audit log path."""
        return self.state_dir / "audit.jsonl"
