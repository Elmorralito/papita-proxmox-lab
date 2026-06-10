"""Process-wide singleton for Proxmox VE settings and HTTP client.

The MCP server and tool implementations share one :class:`~proxmox_ve_mcp.client.http.PveClient`
instance per process. :func:`init_context` is called once at startup (``server.main`` or CLI
entrypoints); tools then obtain the client via :func:`get_client` without threading settings
through every call signature.

Module state is held in module-private ``_client`` and ``_settings`` variables. The design
assumes a single-threaded asyncio stdio server; it is not safe to call :func:`init_context`
concurrently from multiple threads.

Note:
    Callers must invoke :func:`init_context` before :func:`get_client` or :func:`get_settings`.
    The MCP server closes the client on shutdown via :meth:`~proxmox_ve_mcp.client.http.PveClient.aclose`.
"""

from proxmox_ve_mcp.client.http import PveClient
from proxmox_ve_mcp.config import PveSettings

_client: PveClient | None = None
_settings: PveSettings | None = None


def init_context(settings: PveSettings) -> PveClient:
    """Initialize process-wide settings and construct the shared HTTP client.

    Replaces any previously initialized client without explicitly closing the old instance;
    callers should invoke this once per process during startup.

    Args:
        settings: Validated connection and authentication configuration.

    Returns:
        The newly created :class:`~proxmox_ve_mcp.client.http.PveClient` bound to ``settings``.
    """
    global _client, _settings
    _settings = settings
    _client = PveClient(settings)
    return _client


def get_client() -> PveClient:
    """Return the shared Proxmox HTTP client for the current process.

    Returns:
        The client instance created by the most recent :func:`init_context` call.

    Raises:
        RuntimeError: If :func:`init_context` has not been called yet.
    """
    if _client is None:
        raise RuntimeError("PVE client not initialized; call init_context() first")
    return _client


def get_settings() -> PveSettings:
    """Return the Proxmox settings associated with the current process context.

    Returns:
        The :class:`~proxmox_ve_mcp.config.PveSettings` passed to :func:`init_context`.

    Raises:
        RuntimeError: If :func:`init_context` has not been called yet.
    """
    if _settings is None:
        raise RuntimeError("PVE settings not initialized; call init_context() first")
    return _settings
