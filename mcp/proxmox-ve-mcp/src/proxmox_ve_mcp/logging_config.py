"""Structured JSON logging to stderr for the MCP server process.

Configures the ``proxmox_ve_mcp`` logger hierarchy to emit one JSON object per line on
``stderr``, leaving ``stdout`` free for MCP stdio protocol traffic. Tool handlers record
audit-style events (tool name, duration, status) via :func:`log_tool_event` without logging
full API response bodies that may contain secrets.

Public objects:

    JsonStderrFormatter:
        Formats :class:`logging.LogRecord` instances as compact JSON lines.
    configure_logging:
        Installs the stderr handler on the ``proxmox_ve_mcp`` logger at startup.
    log_tool_event:
        Emits a structured tool invocation record for observability and write auditing.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

DEFAULT_LOG_LEVEL = "INFO"
ENV_LOG_LEVEL = "PVE_LOG_LEVEL"
PACKAGE_LOGGER = "proxmox_ve_mcp"
CLI_LOGGER = "proxmox_ve_mcp.cli"


class JsonStderrFormatter(logging.Formatter):
    """Format log records as single-line JSON objects for machine-readable stderr output.

    Each formatted line includes UTC timestamp, level, logger name, and message. Optional
    structured fields from ``record.extra_fields`` (when present) are merged into the
    payload for downstream log aggregation.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Build a JSON string from a log record.

        Args:
            record: Standard library log record to serialize.

        Returns:
            One JSON object encoded as a string (no trailing newline; the handler adds
            line separation). Non-JSON-serializable values in ``extra_fields`` are coerced
            via ``default=str``.
        """
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            payload.update(record.extra_fields)
        return json.dumps(payload, default=str)


def resolve_log_level(value: str | int) -> int:
    """Parse a logging level name or numeric level into an ``logging`` module constant."""
    if isinstance(value, int):
        return value
    cleaned = str(value).strip().upper()
    if not cleaned:
        return logging.INFO
    level = logging.getLevelName(cleaned)
    if isinstance(level, int):
        return level
    raise ValueError(f"Invalid log level: {value!r} (use DEBUG, INFO, WARNING, ERROR)")


def configure_logging(level: str | int | None = None) -> None:
    """Configure the ``proxmox_ve_mcp`` logger to write JSON lines to stderr.

    Replaces any existing handlers on the named logger, disables propagation to the root
    logger, and attaches a :class:`JsonStderrFormatter`. Intended to be called once from
    :mod:`proxmox_ve_mcp.server` or CLI entry points at process startup.

    Args:
        level: Minimum log level. When ``None``, reads ``PVE_LOG_LEVEL`` from the
            environment or defaults to ``INFO``.

    Side Effects:
        Mutates the ``proxmox_ve_mcp`` logger handlers and level in the current process.
    """
    if level is None:
        level = os.environ.get(ENV_LOG_LEVEL, DEFAULT_LOG_LEVEL)
    resolved = resolve_log_level(level)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonStderrFormatter())
    root = logging.getLogger(PACKAGE_LOGGER)
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(resolved)
    root.propagate = False


def configure_cli_logging(level: str | int | None = None) -> logging.Logger:
    """Configure stderr JSON logging and return a plain-text stdout CLI logger."""
    configure_logging(level)
    cli = logging.getLogger(CLI_LOGGER)
    cli.handlers.clear()
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(logging.Formatter("%(message)s"))
    cli.addHandler(stdout_handler)
    cli.setLevel(logging.INFO)
    cli.propagate = False
    return cli


def log_tool_event(
    tool: str,
    *,
    duration_ms: int,
    status: str,
    **fields: Any,
) -> None:
    """Emit a structured audit log entry for an MCP tool invocation.

    Logs at INFO to ``proxmox_ve_mcp.tools``. Additional keyword arguments are merged into
    the JSON payload (for example ``mutating=True`` or guest identifiers on write tools).
    Callers should pass operational metadata only, not raw API responses or credentials.

    Args:
        tool: MCP tool name (for example ``pve_list_nodes``).
        duration_ms: Wall-clock duration of the tool handler in milliseconds.
        status: Outcome label, typically ``ok`` or ``error``.
        **fields: Optional extra key-value pairs included in the JSON ``extra_fields`` block.

    Side Effects:
        Writes one JSON line to stderr via the configured logging handlers.
    """
    logger = logging.getLogger("proxmox_ve_mcp.tools")
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        "(tool)",
        0,
        f"{tool} {status}",
        (),
        None,
    )
    record.extra_fields = {
        "tool": tool,
        "duration_ms": duration_ms,
        "status": status,
        **fields,
    }
    logger.handle(record)
