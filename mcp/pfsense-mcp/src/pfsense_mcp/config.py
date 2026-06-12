"""Environment-backed settings for pfSense RESt API connectivity."""

import ipaddress
from typing import Literal, cast

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from pfsense_mcp.constants import (
    ALLOWED_HASH_ALGOS,
    ALLOWED_LENGTH_BYTES,
    API_PREFIX,
    DEFAULT_API_USER,
    DEFAULT_HASH_ALGO,
    DEFAULT_HTTP_TIMEOUT_SEC,
    DEFAULT_LENGTH_BYTES,
)
from pfsense_mcp.logging_config import resolve_log_level

HashAlgo = Literal["sha256", "sha384", "sha512"]


class PfsSettings(BaseSettings):
    """Load ``PFSENSE_*`` settings from the environment or ``.env``."""

    model_config = SettingsConfigDict(env_prefix="PFSENSE_", extra="ignore")

    host: str = Field(description="pfSense IPv4 or IPv6 address (no hostname/FQDN)")
    port: int = Field(default=443, ge=1, le=65535)
    api_key: str = Field(description="REST API key for X-API-Key header")
    api_user: str = Field(
        default=DEFAULT_API_USER,
        description="Local pfSense user that owns the REST API key (hints and setup docs)",
    )
    verify_ssl: bool = Field(default=True)
    hash_algo: HashAlgo = Field(
        default=cast(HashAlgo, DEFAULT_HASH_ALGO),
        description="Hash algorithm used when creating pfREST API keys (sha256/sha384/sha512)",
    )
    length_bytes: int = Field(
        default=DEFAULT_LENGTH_BYTES,
        description="Key length in bytes when creating pfREST API keys (16/24/32/64)",
    )
    http_timeout_sec: float = Field(
        default=DEFAULT_HTTP_TIMEOUT_SEC,
        ge=1.0,
        le=600.0,
        description="Default HTTP timeout for pfREST GET requests",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level for stderr JSON logs (DEBUG, INFO, WARNING, ERROR)",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Normalize and validate ``PFSENSE_LOG_LEVEL``."""
        resolve_log_level(value)
        return value.strip().upper()

    @field_validator("host")
    @classmethod
    def validate_host_is_ip(cls, value: str) -> str:
        """Require ``PFSENSE_HOST`` to be an IPv4/IPv6 literal without a URL scheme."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("PFSENSE_HOST must not be empty")
        if "://" in cleaned:
            raise ValueError("PFSENSE_HOST must not include a URL scheme")
        try:
            ipaddress.ip_address(cleaned)
        except ValueError as exc:
            raise ValueError(
                "PFSENSE_HOST must be an IPv4 or IPv6 address literal; " "hostnames and FQDNs are not allowed"
            ) from exc
        return cleaned

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str) -> str:
        """Reject empty ``PFSENSE_API_KEY`` values."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("PFSENSE_API_KEY must not be empty")
        return cleaned

    @field_validator("api_user")
    @classmethod
    def validate_api_user(cls, value: str) -> str:
        """Reject empty ``PFSENSE_API_USER`` values."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("PFSENSE_API_USER must not be empty")
        return cleaned

    @field_validator("hash_algo")
    @classmethod
    def validate_hash_algo(cls, value: str) -> str:
        """Validate pfREST key hash algorithm against allowed values."""
        cleaned = value.strip().lower()
        if cleaned not in ALLOWED_HASH_ALGOS:
            allowed = ", ".join(sorted(ALLOWED_HASH_ALGOS))
            raise ValueError(f"PFSENSE_HASH_ALGO must be one of: {allowed}")
        return cleaned

    @field_validator("length_bytes")
    @classmethod
    def validate_length_bytes(cls, value: int) -> int:
        """Validate pfREST key length against allowed byte sizes."""
        if value not in ALLOWED_LENGTH_BYTES:
            allowed = ", ".join(str(item) for item in sorted(ALLOWED_LENGTH_BYTES))
            raise ValueError(f"PFSENSE_LENGTH_BYTES must be one of: {allowed}")
        return value

    @property
    def base_url(self) -> str:
        """pfREST root: ``https://{host}:{port}/api/v2/``."""
        return f"https://{self.host}:{self.port}{API_PREFIX}"

    def api_key_header(self) -> str:
        """Return the raw API key value for the ``X-API-Key`` request header."""
        return self.api_key
