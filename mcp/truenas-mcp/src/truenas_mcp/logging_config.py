"""Structured JSON logging to stderr for the TrueNAS MCP process."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

DEFAULT_LOG_LEVEL = "INFO"
ENV_LOG_LEVEL = "TRUENAS_LOG_LEVEL"
PACKAGE_LOGGER = "truenas_mcp"
CLI_LOGGER = "truenas_mcp.cli"


class JsonStderrFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        """Build a JSON string from a log record."""
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
    """Parse a logging level name or numeric level."""
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
    """Configure the ``truenas_mcp`` logger to write JSON lines to stderr."""
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
    """Emit a structured audit log entry for an MCP tool invocation."""
    logger = logging.getLogger(f"{PACKAGE_LOGGER}.tools")
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
