"""MCP server entrypoint (stdio transport)."""

import asyncio
import logging
import sys

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from truenas_mcp.config import TnasSettings
from truenas_mcp.context import get_client, init_context
from truenas_mcp.logging_config import configure_logging
from truenas_mcp.tools.register import register_tools

logger = logging.getLogger("truenas_mcp.server")
MCP_SERVER_NAME = "truenas"


def create_server() -> FastMCP:
    """Create a FastMCP instance with all v1 tools registered."""
    mcp = FastMCP(MCP_SERVER_NAME)
    register_tools(mcp)
    return mcp


def main() -> None:
    """Load configuration, initialize the client, and run the MCP stdio server."""
    load_dotenv()
    configure_logging()

    try:
        settings = TnasSettings()
    except Exception as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    configure_logging(settings.log_level)

    init_context(settings)
    logger.info(
        "Starting %s MCP server (host=%s ws_uri=%s verify_ssl=%s)",
        MCP_SERVER_NAME,
        settings.host,
        settings.ws_uri,
        settings.verify_ssl,
    )

    mcp = create_server()

    async def _run() -> None:
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
