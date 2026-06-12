"""HTTP client for pfSense REST API."""

from pfsense_mcp.client.errors import PfsApiError
from pfsense_mcp.client.http import PfsClient

__all__ = ["PfsApiError", "PfsClient"]
