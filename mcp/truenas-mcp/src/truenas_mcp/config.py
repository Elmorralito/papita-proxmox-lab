"""Environment-backed settings for TrueNAS WebSocket API connectivity."""

from pathlib import Path
from typing import Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from truenas_mcp.constants import (
    DEFAULT_WS_PATH,
    DEFAULT_WS_TIMEOUT_SEC,
    LAB_HA_POOL_NAME,
    LAB_NFS_EXPORT,
    LAB_SCRUTINY_APP_NAME,
)
from truenas_mcp.logging_config import resolve_log_level


def _read_env_file_value(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    prefix = f"{key}="
    for line in path.read_text(encoding="utf-8").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        if cleaned.startswith(prefix):
            return cleaned.split("=", 1)[1].strip().strip('"').strip("'")
    return None


class TnasSettings(BaseSettings):
    """Load ``TRUENAS_*`` settings from the environment or ``.env``."""

    model_config = SettingsConfigDict(env_prefix="TRUENAS_", extra="ignore")

    host: str = Field(description="TrueNAS hostname or IP (no URL scheme)")
    port: int = Field(default=443, ge=1, le=65535)
    api_key: str = Field(description="TrueNAS API key from My API Keys in the web UI")
    verify_ssl: bool = Field(
        default=False,
        description="Verify TLS certificate (homelab often uses self-signed certs)",
    )
    ws_path: str = Field(
        default=DEFAULT_WS_PATH,
        description="WebSocket path (default /websocket; legacy /api/v2.0/websocket)",
    )
    ws_timeout_sec: float = Field(
        default=DEFAULT_WS_TIMEOUT_SEC,
        ge=5.0,
        le=600.0,
        description="RPC timeout for WebSocket calls",
    )
    ws_ping_interval_sec: float = Field(
        default=30.0,
        ge=0.0,
        le=300.0,
        description="WebSocket ping interval (0 disables explicit ping)",
    )
    lab_nfs_export: str = Field(
        default=LAB_NFS_EXPORT,
        description="Expected NFS export path for Proxmox HA validation",
    )
    lab_ha_pool_name: str = Field(
        default=LAB_HA_POOL_NAME,
        description="Expected ZFS pool name for Proxmox HA",
    )
    lab_scrutiny_app_name: str = Field(
        default=LAB_SCRUTINY_APP_NAME,
        description="Scrutiny app name in app.query",
    )
    lab_config_file: str | None = Field(
        default=None,
        description="Optional path to lab env file (e.g. default.truenas.nfs.env)",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level for stderr JSON logs (DEBUG, INFO, WARNING, ERROR)",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Normalize and validate ``TRUENAS_LOG_LEVEL``."""
        resolve_log_level(value)
        return value.strip().upper()

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        """Reject empty hosts and URL schemes in ``TRUENAS_HOST``."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("TRUENAS_HOST must not be empty")
        if "://" in cleaned:
            raise ValueError("TRUENAS_HOST must not include a URL scheme")
        return cleaned

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str) -> str:
        """Reject empty ``TRUENAS_API_KEY`` values."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("TRUENAS_API_KEY must not be empty")
        if cleaned == "REPLACE_FROM_SECRET_STORE":
            raise ValueError("TRUENAS_API_KEY is still the placeholder; set a real API key")
        return cleaned

    @field_validator("ws_path")
    @classmethod
    def validate_ws_path(cls, value: str) -> str:
        """Ensure WebSocket path starts with ``/``."""
        cleaned = value.strip() or DEFAULT_WS_PATH
        if not cleaned.startswith("/"):
            cleaned = f"/{cleaned}"
        return cleaned

    @model_validator(mode="after")
    def apply_lab_config_overlay(self) -> Self:
        """Overlay lab paths from ``lab_config_file`` when set."""
        if not self.lab_config_file:
            return self
        path = Path(self.lab_config_file).expanduser()
        export = _read_env_file_value(path, "TRUENAS_NFS_EXPORT")
        if export:
            return self.model_copy(update={"lab_nfs_export": export})
        return self

    @property
    def ws_uri(self) -> str:
        """WebSocket URI: ``wss://{host}:{port}{ws_path}``."""
        return f"wss://{self.host}:{self.port}{self.ws_path}"
