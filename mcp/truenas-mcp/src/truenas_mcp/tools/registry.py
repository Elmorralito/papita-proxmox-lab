"""Tool safety classification."""

from enum import Enum


class ToolClass(str, Enum):
    """Safety classification for MCP tools."""

    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


TOOL_REGISTRY: dict[str, ToolClass] = {}
