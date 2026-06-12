"""MCP server entrypoint for Proxmox VE (stdio transport).

Bootstraps environment loading, structured logging, validated :class:`~proxmox_ve_mcp.config.PveSettings`,
and the shared HTTP client before registering MCP tools and serving requests over stdin/stdout.

The console script ``proxmox-ve-mcp`` (see ``pyproject.toml``) invokes :func:`main`. Cursor and
other MCP hosts spawn this process and communicate via the Model Context Protocol on stdio while
operational logs go to stderr.

Module constants:

    MCP_SERVER_NAME:
        Short server identifier passed to FastMCP (``proxmox-ve``); must match Cursor ``mcp.json``
        server key for discoverability.
"""

import asyncio
import logging
import sys

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from proxmox_ve_mcp.config import PveSettings
from proxmox_ve_mcp.context import get_client, init_context
from proxmox_ve_mcp.logging_config import configure_logging
from proxmox_ve_mcp.tools.register import register_tools

logger = logging.getLogger("proxmox_ve_mcp.server")

MCP_SERVER_NAME = "proxmox-ve"


def create_server() -> FastMCP:
    """Construct a FastMCP instance with all Proxmox VE tools registered.

    Returns:
        Configured :class:`~mcp.server.fastmcp.FastMCP` server named :data:`MCP_SERVER_NAME`
        with read and gated write tools attached via :mod:`proxmox_ve_mcp.tools.register`.

    Note:
        Does not load settings or start the client; call :func:`init_context` before serving
        requests so tool handlers can use :func:`~proxmox_ve_mcp.context.get_client`.
    """
    mcp = FastMCP(MCP_SERVER_NAME)
    register_tools(mcp)
    return mcp


def main() -> None:
    """Run the Proxmox VE MCP server until stdin closes or the process is interrupted.

    Loads ``.env`` (if present), configures JSON logging to stderr, validates ``PVE_*``
    settings, initializes the HTTP client context, registers tools, and runs the asyncio
    stdio event loop. The HTTP client is closed on shutdown.

    Side Effects:
        Exits the process with code ``1`` when settings validation fails. Exits ``0`` after
        normal stdio shutdown or ``KeyboardInterrupt``.

    Note:
        Startup logs include host, port, and ``verify_ssl`` but never token secrets.
    """
    load_dotenv()
    configure_logging()

    try:
        settings = PveSettings()
    except Exception as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    configure_logging(settings.log_level)

    init_context(settings)
    logger.info(
        "Starting %s MCP server (host=%s port=%s verify_ssl=%s)",
        MCP_SERVER_NAME,
        settings.host,
        settings.port,
        settings.verify_ssl,
    )

    mcp = create_server()

    async def _run() -> None:
        """Serve MCP over stdio and close the HTTP client on shutdown."""
        try:
            await mcp.run_stdio_async()
        finally:
            await get_client().aclose()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
