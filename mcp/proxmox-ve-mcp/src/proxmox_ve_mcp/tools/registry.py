"""Tool safety classification and metadata.

Defines read/write/destructive categories for MCP tools and a registry populated at
registration time by :func:`~proxmox_ve_mcp.tools.register.register_tools`.
"""

from enum import Enum


class ToolClass(str, Enum):
    """Safety classification for MCP tools exposed to agents.

    Values are serialized into tool response ``meta.tool_class`` for client-side policy.
    """

    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


TOOL_REGISTRY: dict[str, ToolClass] = {}
"""Maps registered tool names to their :class:`ToolClass`; filled by ``register_tools``."""
