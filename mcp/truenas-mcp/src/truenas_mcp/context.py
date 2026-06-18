"""Process-wide TrueNAS settings and WebSocket client singleton."""

from truenas_mcp.client.websocket import TnasClient
from truenas_mcp.config import TnasSettings

_client: TnasClient | None = None
_settings: TnasSettings | None = None


def init_context(settings: TnasSettings) -> TnasClient:
    """Initialize process-wide settings and WebSocket client singletons."""
    global _client, _settings
    _settings = settings
    _client = TnasClient(settings)
    return _client


def get_client() -> TnasClient:
    """Return the initialized TrueNAS WebSocket client."""
    if _client is None:
        raise RuntimeError("TrueNAS client not initialized; call init_context() first")
    return _client


def get_settings() -> TnasSettings:
    """Return the initialized TrueNAS settings loaded from the environment."""
    if _settings is None:
        raise RuntimeError("TrueNAS settings not initialized; call init_context() first")
    return _settings
