"""Process-wide pfSense settings and HTTP client singleton."""

from pfsense_mcp.client.http import PfsClient
from pfsense_mcp.config import PfsSettings

_client: PfsClient | None = None
_settings: PfsSettings | None = None


def init_context(settings: PfsSettings) -> PfsClient:
    """Initialize process-wide settings and HTTP client singletons."""
    global _client, _settings
    _settings = settings
    _client = PfsClient(settings)
    return _client


def get_client() -> PfsClient:
    """Return the initialized pfREST HTTP client."""
    if _client is None:
        raise RuntimeError("PFS client not initialized; call init_context() first")
    return _client


def get_settings() -> PfsSettings:
    """Return the initialized pfSense settings loaded from the environment."""
    if _settings is None:
        raise RuntimeError("PFS settings not initialized; call init_context() first")
    return _settings
