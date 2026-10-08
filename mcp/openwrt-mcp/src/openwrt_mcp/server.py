"""MCP server entrypoint (stdio transport)."""

import asyncio
import logging
import sys

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from openwrt_mcp.config import OpenwrtSettings
from openwrt_mcp.context import init_context
from openwrt_mcp.logging_config import configure_logging
from openwrt_mcp.tools.register import register_tools

logger = logging.getLogger("openwrt_mcp.server")
MCP_SERVER_NAME = "openwrt"


def create_server() -> FastMCP:
    """Create a FastMCP instance with all tools registered."""
    mcp = FastMCP(MCP_SERVER_NAME)
    register_tools(mcp)
    return mcp


def main() -> None:
    """Load configuration, initialise the context and run the stdio server."""
    load_dotenv()
    configure_logging()
    try:
        settings = OpenwrtSettings()
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Configuration error: %s", exc.__class__.__name__)
        sys.exit(1)
    configure_logging(settings.log_level)
    init_context(settings)
    logger.info("Starting %s MCP server (router=%s host=%s)", MCP_SERVER_NAME, settings.router_id, settings.host)
    mcp = create_server()
    try:
        asyncio.run(mcp.run_stdio_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
