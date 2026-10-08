"""Stderr logging (stdout is reserved for the MCP stdio protocol)."""

import logging
import sys

_VALID = {"DEBUG", "INFO", "WARNING", "ERROR"}


def resolve_log_level(value: str) -> int:
    """Map a level name to a ``logging`` constant, rejecting unknown names."""
    name = value.strip().upper()
    if name not in _VALID:
        raise ValueError(f"Invalid log level {value!r}; use one of {sorted(_VALID)}")
    return getattr(logging, name)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging to stderr."""
    logging.basicConfig(
        level=resolve_log_level(level),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
