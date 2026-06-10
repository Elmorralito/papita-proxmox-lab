"""Build standard tool response metadata for MCP tool JSON payloads.

Assembles the ``meta`` object included in every tool success or error response, attaching
tool name, duration, safety classification, and optional runbook references.
"""

from typing import Any

from proxmox_ve_mcp.constants import RUNBOOK_REFS
from proxmox_ve_mcp.tools.registry import TOOL_REGISTRY


def tool_meta(tool: str, duration_ms: int, **extra: Any) -> dict[str, Any]:
    """Build the ``meta`` block for a tool JSON response.

    Looks up :data:`~proxmox_ve_mcp.tools.registry.TOOL_REGISTRY` for ``tool_class`` and
    :data:`~proxmox_ve_mcp.constants.RUNBOOK_REFS` for ``runbook_ref`` when defined.

    Args:
        tool: Registered MCP tool name (for example ``pve_list_nodes``).
        duration_ms: Wall-clock execution time in milliseconds.
        **extra: Additional key-value pairs merged into the metadata dict last.

    Returns:
        Dictionary with at least ``tool`` and ``duration_ms``; may include ``tool_class``,
        ``runbook_ref``, and any *extra* fields.
    """
    meta: dict[str, Any] = {"tool": tool, "duration_ms": duration_ms}
    tool_class = TOOL_REGISTRY.get(tool)
    if tool_class is not None:
        meta["tool_class"] = tool_class.value
    runbook = RUNBOOK_REFS.get(tool)
    if runbook:
        meta["runbook_ref"] = runbook
    meta.update(extra)
    return meta
