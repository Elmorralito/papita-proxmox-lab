"""Pydantic settings for Proxmox VE API connectivity and authentication.

This module defines :class:`PveSettings`, which loads connection parameters from
environment variables prefixed with ``PVE_`` (or from a ``.env`` file when used with
``python-dotenv`` at process startup). Settings are consumed by the HTTP client and
MCP server entrypoints to build the REST base URL and ``PVEAPIToken`` authorization
header.

Authentication supports either a single combined token string
(``PVE_API_TOKEN``) or split fields (``PVE_USER``, ``PVE_TOKEN_ID``,
``PVE_TOKEN_SECRET``). Host validation rejects empty values and URL schemes so
``PVE_HOST`` remains a bare hostname or IP address.
"""

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from proxmox_ve_mcp.constants import API_PREFIX
from proxmox_ve_mcp.logging_config import resolve_log_level


class PveSettings(BaseSettings):
    """Load and validate Proxmox VE API connection settings from the environment.

    Environment variables use the ``PVE_`` prefix (for example ``PVE_HOST`` maps to
    ``host``). Unknown keys are ignored. Instantiation raises :class:`pydantic.ValidationError`
    when required fields are missing or validation rules fail.

    Attributes:
        host: Proxmox node hostname or IP reachable on ``port`` (no ``https://`` scheme).
        port: HTTPS API port; Proxmox defaults to ``8006``.
        user: PVE account name with realm, e.g. ``mcp-agent@pam``; required with split-token auth.
        token_id: API token identifier when using split-token auth.
        token_secret: API token secret value when using split-token auth.
        api_token: Full token string ``USER@REALM!TOKENID=SECRET``; alternative to split fields.
        verify_ssl: When ``True``, TLS certificate verification is enabled for HTTPS requests.
    """

    model_config = SettingsConfigDict(env_prefix="PVE_", extra="ignore")

    host: str = Field(description="Proxmox host (IP or DNS, no scheme)")
    port: int = Field(default=8006, ge=1, le=65535)
    user: str | None = Field(default=None, description="API user, e.g. mcp-agent@pam")
    token_id: str | None = Field(default=None, description="API token identifier")
    token_secret: str | None = Field(default=None, description="API token secret value")
    api_token: str | None = Field(
        default=None,
        description="Full token as USER@REALM!TOKENID=SECRET (alternative to split fields)",
    )
    verify_ssl: bool = Field(default=True, description="Verify TLS certificate on :8006")
    log_level: str = Field(
        default="INFO",
        description="Logging level for stderr JSON logs (DEBUG, INFO, WARNING, ERROR)",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Normalize and validate ``PVE_LOG_LEVEL``."""
        resolve_log_level(value)
        return value.strip().upper()

    @field_validator("host")
    @classmethod
    def strip_host(cls, value: str) -> str:
        """Normalize and validate ``host`` after loading from the environment.

        Args:
            value: Raw host string, typically from ``PVE_HOST``.

        Returns:
            Stripped hostname or IP without leading or trailing whitespace.

        Raises:
            ValueError: If ``value`` is empty after stripping or contains a URL scheme
                (``://``), which belongs in the client base URL rather than ``host``.
        """
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("PVE_HOST must not be empty")
        if "://" in cleaned:
            raise ValueError("PVE_HOST must not include a URL scheme")
        return cleaned

    @model_validator(mode="after")
    def validate_auth(self) -> "PveSettings":
        """Ensure at least one complete authentication configuration is present.

        Accepts either ``api_token`` alone or all three split fields together. Partial
        split configuration (for example user and token_id without secret) is rejected.

        Returns:
            The validated settings instance.

        Raises:
            ValueError: When neither ``api_token`` nor the full split-token triplet is set.
        """
        if self.api_token:
            return self
        if self.user and self.token_id and self.token_secret:
            return self
        raise ValueError("Set PVE_API_TOKEN or all of PVE_USER, PVE_TOKEN_ID, and PVE_TOKEN_SECRET")

    @property
    def base_url(self) -> str:
        """Build the Proxmox JSON API base URL for HTTP clients.

        Returns:
            HTTPS URL including host, port, and :data:`~proxmox_ve_mcp.constants.API_PREFIX`
            (typically ``https://{host}:{port}/api2/json``).
        """
        return f"https://{self.host}:{self.port}{API_PREFIX}"

    def authorization_header(self) -> str:
        """Format the ``Authorization`` header value for Proxmox API token auth.

        Uses ``PVEAPIToken=`` prefix required by the Proxmox REST API. When split-token
        fields were validated at construction time, ``user``, ``token_id``, and
        ``token_secret`` are guaranteed non-``None``.

        Returns:
            Header value suitable for ``Authorization``, e.g.
            ``PVEAPIToken=mcp-agent@pam!cursor=secret`` or the verbatim ``api_token``
            string when that form was configured.

        Raises:
            AssertionError: If split-token mode was used but an internal invariant is
                violated (should not occur after successful validation).
        """
        if self.api_token:
            return f"PVEAPIToken={self.api_token}"
        assert self.user and self.token_id and self.token_secret
        return f"PVEAPIToken={self.user}!{self.token_id}={self.token_secret}"
